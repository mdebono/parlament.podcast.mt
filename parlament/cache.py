import pickle
from pathlib import Path
from curl_cffi import requests

CACHE_PATH = 'cache.pkl'

# Session that impersonates Chrome at the TLS and HTTP level.
# Parliament.mt uses WAF/bot detection based on TLS fingerprinting (JA3): a
# request with Chrome HTTP headers but Python's TLS signature is flagged as a
# bot and blocked with 403. curl-cffi makes the TLS handshake and HTTP/2
# settings identical to real Chrome, bypassing this check.
_session = requests.Session(impersonate="chrome136")

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
    response = _session.get(url)
    if not response.ok:
        print('Warning: page fetch returned HTTP {}: {}'.format(response.status_code, url))

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
        response = _session.get(url, headers=headers)
        cache[key] = response
        print('GET added to cache: {}'.format(url))
        write_cache()
        return response

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
        response = _session.post(url, data=payload, headers=headers)
        cache[key] = response
        print('POST added to cache: {} with POST {}'.format(url, payload))
        write_cache()
        return response

cache = read_cache()
