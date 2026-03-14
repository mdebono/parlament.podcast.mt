import atexit
import json as _json
import pickle
from pathlib import Path
from curl_cffi import requests

CACHE_PATH = 'cache.pkl'
HTTP_TIMEOUT = 30  # seconds

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

def httpFetch(url):
    """Fetch an HTML page without caching, used to establish session cookies."""
    print('Fetching (no cache): {}'.format(url))
    response = _session.get(url, timeout=HTTP_TIMEOUT)
    if not response.ok:
        print('Warning: page fetch returned HTTP {}: {}'.format(response.status_code, url))

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
        response = _session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        cache[key] = _to_cached(response)
        print('GET added to cache: {}'.format(url))
        write_cache()
        return cache[key]

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
        response = _session.post(url, data=payload, headers=headers, timeout=HTTP_TIMEOUT)
        cache[key] = _to_cached(response)
        print('POST added to cache: {} with POST {}'.format(url, payload))
        write_cache()
        return cache[key]

cache = read_cache()
# HEAD responses are batched and written once at process exit. Note: atexit
# handlers do not run on abnormal termination (SIGKILL, hard crash). In that
# case the HEAD entries are simply re-fetched on the next run.
atexit.register(write_cache)
