# parlament.mt sitting -> Spotify episode map
#
# Powers the parlament.podcast.mt/parlament.mt/<sitting path> shortcut (and
# podcast.mt/parlament.mt/..., which forwards here): public/404.html looks
# the path up in parlament-spotify.json and redirects to the episode.
#
# Every catalogued episode carries its parlament.mt sitting link, and Spotify
# publishes each feed item under the same title, so:
#   entry['link'] -> entry['title'] -> Spotify episode with that name
#
# Spotify episodes are listed through the Web API (client-credentials flow),
# which needs SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET. The map is kept in
# R2 next to the catalogue and only ever grows, so a run without credentials
# or with Spotify unreachable still publishes every previously matched
# episode.

import base64
import json
import os
import re
import sys
import unicodedata

from curl_cffi import requests

from parlament import mirror

SHOW_ID = '41wjGno413H9zT7NEJZxs6'
SHOW_URL = 'https://open.spotify.com/show/' + SHOW_ID
MAP_KEY = 'catalog/spotify.json'
MARKET = 'MT'
PAGE_SIZE = 50
HTTP_TIMEOUT = 30  # seconds

_PARLAMENT_URL_RE = re.compile(
    r'^/*(?:https?:/*)?(?:www\.)?parlament\.mt(?=[/?#]|$)(?:/([^?#]*))?',
    re.IGNORECASE)

def parlament_key(url):
    """Lookup key for a parlament.mt URL (or a path that embeds one): the
    path without language prefix, trailing slash, query or fragment,
    lowercased. The site serves a sitting under /mt/..., /en/... and bare
    /..., so all of them map to the same key:
      https://parlament.mt/mt/15th-leg/plenary-session/ps-017-04092026-0930-am/
      -> 15th-leg/plenary-session/ps-017-04092026-0930-am
    Returns None for anything that isn't a parlament.mt address.

    Keep in sync with the copy in public/404.html."""
    m = _PARLAMENT_URL_RE.match(str(url).strip())
    if not m:
        return None
    segments = [s for s in (m.group(1) or '').lower().split('/') if s]
    if segments and segments[0] in ('mt', 'en'):
        segments = segments[1:]
    return '/'.join(segments)

def _norm_title(title):
    return ' '.join(unicodedata.normalize('NFC', title or '').split()).lower()

def _get_token(client_id, client_secret):
    credentials = base64.b64encode(
        '{}:{}'.format(client_id, client_secret).encode()).decode()
    response = requests.post(
        'https://accounts.spotify.com/api/token',
        headers={'Authorization': 'Basic ' + credentials},
        data={'grant_type': 'client_credentials'},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()['access_token']

def get_show_episodes(client_id, client_secret):
    """Every episode of the show on Spotify as (name, url) pairs."""
    token = _get_token(client_id, client_secret)
    episodes = []
    url = 'https://api.spotify.com/v1/shows/{}/episodes?market={}&limit={}'.format(
        SHOW_ID, MARKET, PAGE_SIZE)
    while url:
        response = requests.get(url, headers={'Authorization': 'Bearer ' + token},
                                timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        page = response.json()
        for episode in page.get('items') or []:
            if episode and episode.get('external_urls', {}).get('spotify'):
                episodes.append((episode['name'], episode['external_urls']['spotify']))
        url = page.get('next')
    return episodes

def match_episodes(entries, spotify_episodes):
    """{parlament_key: spotify url} for catalogue entries whose title has a
    Spotify episode. Entries not on Spotify yet are simply left out."""
    by_title = {_norm_title(name): url for name, url in spotify_episodes}
    matched = {}
    for entry in entries:
        key = parlament_key(entry.get('link') or '')
        url = by_title.get(_norm_title(entry.get('title')))
        if key and url:
            matched[key] = url
    return matched

def load_map():
    try:
        return mirror.get_json(MAP_KEY)
    except mirror.ObjectNotFound:
        return {}

def update_map(store):
    """Refresh the map from Spotify, persist it to R2 and return it.

    Never raises: the map is a convenience and must not fail the run that
    publishes the feed. On any failure the previously stored map is
    returned (empty if there is none or R2 is unreadable)."""
    try:
        episodes = load_map()
    except Exception as e:
        print('Warning: could not load Spotify map: {}'.format(e), file=sys.stderr)
        return {}

    client_id = os.environ.get('SPOTIFY_CLIENT_ID')
    client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
    if not client_id or not client_secret:
        print('Warning: SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET not set; '
              'Spotify map not refreshed', file=sys.stderr)
        return episodes

    try:
        spotify_episodes = get_show_episodes(client_id, client_secret)
        entries = list(store['episodes'].values())
        matched = match_episodes(entries, spotify_episodes)
        updated = dict(episodes, **matched)
        if updated != episodes:
            mirror.put_json(MAP_KEY, updated)
        print('Spotify map: {} episode(s) mapped; {} catalogued, {} on Spotify'.format(
            len(updated), len(entries), len(spotify_episodes)))
        return updated
    except Exception as e:
        print('Warning: Spotify map not refreshed: {}'.format(e), file=sys.stderr)
        return episodes

def write_map(episodes, filename):
    """Write the map in the shape public/404.html expects."""
    with open(filename, 'w', encoding='utf8') as fp:
        json.dump({'showUrl': SHOW_URL, 'episodes': episodes}, fp,
                  ensure_ascii=False, indent=2, sort_keys=True)
        fp.write('\n')
