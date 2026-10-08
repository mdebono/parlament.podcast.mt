import atexit
import json as _json
import os
import pickle
import time
from pathlib import Path
from urllib.parse import quote
import requests

CACHE_PATH = 'cache.pkl'
HTTP_TIMEOUT = 30  # seconds
# Transient server trouble only. After a 403 no further requests are sent in
# this run (see _refused); the next run tries again.
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (1, 2)  # delays before the 2nd and 3rd attempts
GAP_SECONDS = float(os.environ.get('PARLAMENT_GAP', '2'))  # between requests

# Our own user-agent, naming the podcast.
USER_AGENT = 'Il-Podcast tal-Parlament/1.0 https://parlament.podcast.mt'

# In CI every request goes through the fetch Worker (fetch/README.md):
# PARLAMENT_VIA is its address; unset, requests go straight to parlament.mt.
# PARLAMENT_VIA_KEY, if set, is sent as x-fetch-key.
VIA = os.environ.get('PARLAMENT_VIA', '').rstrip('/')
VIA_KEY = os.environ.get('PARLAMENT_VIA_KEY', '')

_session = requests.Session()
_session.headers['User-Agent'] = USER_AGENT
_last_request = None  # time.monotonic() of the last request sent
_refused = None       # description of the first 403


class _CachedResponse:
    """Picklable snapshot of an HTTP response.

    Only the data fields we need are kept, so the cache can be pickled; it
    exposes the subset of the requests.Response interface used by callers.
    """
    def __init__(self, status_code, content, url, headers=None):
        self.status_code = status_code
        self.content = content
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            raise requests.exceptions.HTTPError(
                '{} Client Error for url: {}'.format(self.status_code, self.url)
            )
        elif 500 <= self.status_code < 600:
            raise requests.exceptions.HTTPError(
                '{} Server Error for url: {}'.format(self.status_code, self.url)
            )

    def json(self):
        return _json.loads(self.content)


def _to_cached(response):
    """Convert a live requests Response to a picklable _CachedResponse."""
    return _CachedResponse(
        response.status_code,
        response.content,
        str(response.url),
        {k.lower(): v for k, v in response.headers.items()},
    )


class _FileDownloadMeta:
    """Picklable metadata for a file downloaded via httpGetFile.

    Kept separate from _CachedResponse so the two types cannot be mistaken:
    _CachedResponse.content is bytes; _FileDownloadMeta.file_path is a str.
    """
    def __init__(self, status_code, file_path, url, headers=None):
        self.status_code = status_code
        self.file_path = file_path
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            raise requests.exceptions.HTTPError(
                '{} Client Error for url: {}'.format(self.status_code, self.url)
            )
        elif 500 <= self.status_code < 600:
            raise requests.exceptions.HTTPError(
                '{} Server Error for url: {}'.format(self.status_code, self.url)
            )

def _request(method, url, referer=None, stream=False):
    """Send one request for *url* to parlament.mt: through the fetch Worker
    when PARLAMENT_VIA is set, else directly. *method* is GET, HEAD or POST
    (a POST without a body, to parlament.mt's JSON API)."""
    global _last_request
    if _last_request is not None:
        wait = GAP_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
    _last_request = time.monotonic()
    headers = {'Accept': 'application/json, text/javascript, */*; q=0.01'}
    if not VIA:
        if referer:
            headers['Referer'] = referer
        if method == 'POST':
            headers['X-Requested-With'] = 'XMLHttpRequest'
        return _session.request(method, url, headers=headers, timeout=HTTP_TIMEOUT,
                                stream=stream, allow_redirects=True)
    via_url = VIA + '/?u=' + quote(url, safe='')
    if method != 'GET':
        via_url += '&m=' + method
    if referer:
        via_url += '&ref=' + quote(referer, safe='')
    if VIA_KEY:
        headers['x-fetch-key'] = VIA_KEY
    response = _session.get(via_url, headers=headers, timeout=HTTP_TIMEOUT, stream=stream)
    if method == 'HEAD' and response.status_code == 200:
        # The Worker answers a HEAD with JSON describing parlament.mt's answer.
        info = response.json()
        meta = {}
        if info.get('bytes'):
            meta['content-length'] = str(info['bytes'])
        if info.get('type'):
            meta['content-type'] = info['type']
        meta['x-fetch-colo'] = info.get('colo') or ''
        meta['x-fetch-ray'] = info.get('cf_ray') or ''
        return _CachedResponse(info['status'], b'', info.get('url') or url, meta)
    response.url = url  # parlament.mt's address, not the Worker's, in errors and the cache
    return response

def _served_from(response):
    """', Worker colo X, cf-ray Y' for a response that came through the fetch Worker, else ''."""
    headers = response.headers or {}
    colo, ray = headers.get('x-fetch-colo'), headers.get('x-fetch-ray')
    return ', Worker colo {}, cf-ray {}'.format(colo or 'unknown', ray or 'unknown') if VIA else ''

def _send_with_retry(method, url, description, referer=None, stream=False):
    """Send a request, retrying with backoff on transient server errors.
    A 403 is not retried, and once one is seen no further requests are sent
    in this run; the caller gets a 403 response either way."""
    global _refused
    if _refused:
        print('Warning: not sending {}: parlament.mt refused {}'.format(description, _refused))
        unsent = _CachedResponse(403, b'', url)
        unsent.unsent = True
        return unsent
    response = _request(method, url, referer, stream)
    for delay in RETRY_BACKOFF_SECONDS:
        if response.status_code not in RETRY_STATUS_CODES:
            break
        print('Warning: {} returned HTTP {}, retrying in {}s'.format(
            description, response.status_code, delay))
        if hasattr(response, 'close'):
            response.close()
        time.sleep(delay)
        response = _request(method, url, referer, stream)
    if response.status_code == 403:
        _refused = description
        print('Warning: {} refused with HTTP 403{}{}; no more requests this run'.format(
            description, ' (via {})'.format(VIA) if VIA else '', _served_from(response)))
    return response

def _remember(key, response):
    """Cache *response* under *key* (as a picklable snapshot) and return the
    snapshot. A request not sent after a refusal is returned, not cached, so
    a cache.pkl kept between runs asks for it again next time."""
    snapshot = response if isinstance(response, _CachedResponse) else _to_cached(response)
    if not getattr(snapshot, 'unsent', False):
        cache[key] = snapshot
    return snapshot

def read_cache():
    print('reading cache')
    if Path(CACHE_PATH).exists():
        with open(CACHE_PATH, 'rb') as f:
            cache = pickle.load(f)
            print('cache loaded')
    else:
        cache = {}
        print('new cache created')
    return cache

def write_cache():
    with open(CACHE_PATH, 'wb') as f:
        pickle.dump(cache, f, pickle.HIGHEST_PROTOCOL)
        print('cache written')

def httpHead(url):
    key = ('HEAD', url)
    if key in cache:
        print('HEAD from cache: {}'.format(url))
        return cache[key]
    else:
        response = _send_with_retry('HEAD', url, 'HEAD {}'.format(url))
        if not 200 <= response.status_code < 300:
            print('Warning: HEAD request returned HTTP {}: {}'.format(response.status_code, url))
        print('HEAD added to cache: {}'.format(url))
        return _remember(key, response)
    
def httpGet(url, referer=None):
    key = ('GET', url)
    if key in cache:
        print('GET from cache: {}'.format(url))
        return cache[key]
    else:
        response = _send_with_retry('GET', url, 'GET {}'.format(url), referer)
        snapshot = _remember(key, response)
        print('GET added to cache: {}'.format(url))
        write_cache()
        return snapshot

def httpGetFile(url, file_path, referer=None):
    """
    Download a file from url, store content in file_path, cache only metadata (status, headers, url, file_path).
    If already cached, skip download and return cached metadata.
    """
    key = ('GETFILE', url, file_path)
    if key in cache and Path(file_path).exists():
        print(f'GETFILE from cache: {url} -> {file_path}')
        return cache[key]
    else:
        response = _send_with_retry('GET', url, 'GETFILE {}'.format(url), referer, stream=True)
        with open(file_path, 'wb') as f:
            if isinstance(response, _CachedResponse):
                f.write(response.content)
            else:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        meta = _FileDownloadMeta(
            response.status_code,
            file_path,
            str(response.url),
            {k.lower(): v for k, v in response.headers.items()},
        )
        if not getattr(response, 'unsent', False):
            cache[key] = meta
        print(f'GETFILE added to cache: {url} -> {file_path}')
        write_cache()
        return meta

def httpPost(url, payload, referer=None):
    key = ('POST', payload, url)
    if key in cache:
        print('POST from cache: {} with POST {}'.format(url, payload))
        return cache[key]
    else:
        if payload is not None:
            # the fetch Worker only forwards POSTs without a body
            raise ValueError('httpPost sends no body; got payload {!r}'.format(payload))
        response = _send_with_retry('POST', url, 'POST {}'.format(url), referer)
        snapshot = _remember(key, response)
        print('POST added to cache: {}'.format(url))
        write_cache()
        return snapshot

cache = read_cache()
# HEAD responses are batched and written once at process exit. Note: atexit
# handlers do not run on abnormal termination (SIGKILL, hard crash). In that
# case the HEAD entries are simply re-fetched on the next run.
atexit.register(write_cache)
