import pickle
from pathlib import Path
import requests

CACHE_PATH = 'cache.pkl'

# Persistent session so cookies are shared across requests within a run.
# Only set headers that are safe to send on every request type (page loads
# and AJAX alike). Do NOT include X-Requested-With here — real browsers only
# send that header on AJAX calls, never on normal page loads.
_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
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
    """Fetch an HTML page without caching, used to establish session cookies."""
    print('Fetching (no cache): {}'.format(url))
    response = _session.get(url, headers={
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Upgrade-Insecure-Requests': '1',
    })
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
