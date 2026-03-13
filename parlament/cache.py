import pickle
from pathlib import Path
import requests

CACHE_PATH = 'cache.pkl'

# Persistent session so cookies are shared across requests within a run
_session = requests.Session()
_session.headers.update({
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
})

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
    """Fetch a page without caching, used to establish session cookies."""
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
        headers = {}
        if referer:
            headers['Referer'] = referer
        response = _session.get(url, headers=headers)
        cache[key] = response
        print('GET added to cache: {}'.format(url))
        write_cache()
        return response

def httpPost(url, data, payload):
    key = ('POST', data, url)
    if key in cache:
        print('POST from cache: {} with POST {}'.format(url, data))
        return cache[key]
    else:
        response = _session.post(url, data=payload)
        cache[key] = response
        print('POST added to cache: {} with POST {}'.format(url, data))
        write_cache()
        return response

cache = read_cache()
