import atexit
import json as _json
import pickle
import time
from pathlib import Path
from curl_cffi import requests

CACHE_PATH = 'cache.pkl'
HTTP_TIMEOUT = 30  # seconds
RETRY_STATUS_CODES = {403, 429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (1, 2)  # delays before the 2nd and 3rd attempts

# Session that impersonates Chrome at the TLS and HTTP level.
# Parliament.mt uses WAF/bot detection based on TLS fingerprinting (JA3): a
# request with Chrome HTTP headers but Python's TLS signature is flagged as a
# bot and blocked with 403. curl-cffi makes the TLS handshake and HTTP/2
# settings identical to real Chrome, bypassing this check.
_session = requests.Session(impersonate="chrome136")


class _CachedResponse:
    """Picklable snapshot of an HTTP response.

    curl_cffi Response objects hold CFFI C-extension references that cannot be
    pickled. This class stores only the data fields we need and exposes the
    same subset of the requests.Response interface used by callers.
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
    """Convert a live curl_cffi Response to a picklable _CachedResponse."""
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

def _send_with_retry(send, description):
    """Call *send* (a zero-arg request-issuing callable) and retry with
    backoff if the response status looks like a transient WAF block."""
    response = send()
    for delay in RETRY_BACKOFF_SECONDS:
        if response.status_code not in RETRY_STATUS_CODES:
            break
        print('Warning: {} returned HTTP {}, retrying in {}s'.format(
            description, response.status_code, delay))
        time.sleep(delay)
        response = send()
    return response

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
        response = _session.head(url, timeout=HTTP_TIMEOUT)
        if not response.ok:
            print('Warning: HEAD request returned HTTP {}: {}'.format(response.status_code, url))
        cache[key] = _to_cached(response)
        print('HEAD added to cache: {}'.format(url))
        return cache[key]
    
def httpGet(url, referer=None):
    key = ('GET', url)
    if key in cache:
        print('GET from cache: {}'.format(url))
        return cache[key]
    else:
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
        }
        if referer:
            headers['Referer'] = referer
        response = _send_with_retry(
            lambda: _session.get(url, headers=headers, timeout=HTTP_TIMEOUT),
            'GET {}'.format(url),
        )
        cache[key] = _to_cached(response)
        print('GET added to cache: {}'.format(url))
        write_cache()
        return cache[key]

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
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
        }
        if referer:
            headers['Referer'] = referer
        response = _session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        with open(file_path, 'wb') as f:
            f.write(response.content)
        meta = _FileDownloadMeta(
            response.status_code,
            file_path,
            str(response.url),
            {k.lower(): v for k, v in response.headers.items()},
        )
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
        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
        }
        if referer:
            headers['Referer'] = referer
        response = _send_with_retry(
            lambda: _session.post(url, data=payload, headers=headers, timeout=HTTP_TIMEOUT),
            'POST {} with POST {}'.format(url, payload),
        )
        cache[key] = _to_cached(response)
        print('POST added to cache: {} with POST {}'.format(url, payload))
        write_cache()
        return cache[key]

cache = read_cache()
# HEAD responses are batched and written once at process exit. Note: atexit
# handlers do not run on abnormal termination (SIGKILL, hard crash). In that
# case the HEAD entries are simply re-fetched on the next run.
atexit.register(write_cache)
