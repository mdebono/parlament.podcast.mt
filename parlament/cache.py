import pickle
from pathlib import Path
import requests

CACHE_PATH = 'cache.pkl'

DEFAULT_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'parlament.podcast.mt/1.0 (+https://github.com/mdebono/parlament.podcast.mt)',
}

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

def httpGet(url):
    key = ('GET', url)
    if key in cache:
        print('GET from cache: {}'.format(url))
        return cache[key]
    else:
        response = requests.get(url, headers=DEFAULT_HEADERS)
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
        response = requests.post(url, data=payload)
        cache[key] = response
        print('POST added to cache: {} with POST {}'.format(url, data))
        write_cache()
        return response

cache = read_cache()
