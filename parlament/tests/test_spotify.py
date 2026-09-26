import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from parlament import spotify, mirror

_PS17 = 'https://parlament.mt/mt/15th-leg/plenary-session/ps-017-04092026-0930-am/'
_PS17_KEY = '15th-leg/plenary-session/ps-017-04092026-0930-am'

def _entry(title, link):
    return {'title': title, 'link': link}

def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


class TestParlamentKey(unittest.TestCase):

    def test_language_variants_share_a_key(self):
        for url in (_PS17,
                    'https://parlament.mt/en/15th-leg/plenary-session/ps-017-04092026-0930-am',
                    'https://parlament.mt/15th-leg/plenary-session/ps-017-04092026-0930-am/',
                    'http://www.parlament.mt/15th-leg/Plenary-Session/PS-017-04092026-0930-am?x=1#y'):
            self.assertEqual(spotify.parlament_key(url), _PS17_KEY, url)

    def test_paths_embedding_the_url(self):
        # what the 404 page sees as location.pathname
        for path in ('/parlament.mt/mt/15th-leg/plenary-session/ps-017-04092026-0930-am/',
                     '/https://parlament.mt/15th-leg/plenary-session/ps-017-04092026-0930-am',
                     '/https:/parlament.mt/15th-leg/plenary-session/ps-017-04092026-0930-am'):
            self.assertEqual(spotify.parlament_key(path), _PS17_KEY, path)

    def test_bare_site_is_empty_key(self):
        self.assertEqual(spotify.parlament_key('/parlament.mt'), '')
        self.assertEqual(spotify.parlament_key('https://parlament.mt/mt/'), '')

    def test_other_hosts(self):
        for url in ('/about', '/parlament.mtx/foo', 'https://example.com/parlament.mt/x', ''):
            self.assertIsNone(spotify.parlament_key(url), url)


class TestMatchEpisodes(unittest.TestCase):

    def test_matches_by_title(self):
        entries = [
            _entry('Sessjoni Plenarja S15E017', _PS17),
            _entry('Sessjoni Plenarja S15E018',
                   'https://parlament.mt/mt/15th-leg/plenary-session/ps-018-07092026-0400-pm/'),
            _entry('No link', None),
        ]
        spotify_episodes = [
            ('Sessjoni  Plenarja s15e017 ', 'https://open.spotify.com/episode/A'),
            ('No link', 'https://open.spotify.com/episode/C'),
        ]
        self.assertEqual(spotify.match_episodes(entries, spotify_episodes),
                         {_PS17_KEY: 'https://open.spotify.com/episode/A'})


class TestGetShowEpisodes(unittest.TestCase):

    def test_follows_pagination_and_skips_nulls(self):
        pages = [
            _response({'items': [{'name': 'E1', 'external_urls': {'spotify': 'u1'}}, None],
                       'next': 'https://api.spotify.com/next'}),
            _response({'items': [{'name': 'E2', 'external_urls': {'spotify': 'u2'}}],
                       'next': None}),
        ]
        with patch('parlament.spotify.requests.post',
                   return_value=_response({'access_token': 'T'})) as post, \
             patch('parlament.spotify.requests.get', side_effect=pages) as get:
            episodes = spotify.get_show_episodes('id', 'secret')
        self.assertEqual(episodes, [('E1', 'u1'), ('E2', 'u2')])
        self.assertEqual(post.call_args.kwargs['data'], {'grant_type': 'client_credentials'})
        self.assertIn('market=MT', get.call_args_list[0].args[0])
        self.assertEqual(get.call_args_list[1].args[0], 'https://api.spotify.com/next')
        self.assertEqual(get.call_args.kwargs['headers'], {'Authorization': 'Bearer T'})


class TestUpdateMap(unittest.TestCase):

    _STORE = {'episodes': {'k': _entry('Sessjoni Plenarja S15E017', _PS17)}}
    _ENV = {'SPOTIFY_CLIENT_ID': 'id', 'SPOTIFY_CLIENT_SECRET': 'secret'}

    def test_merges_into_stored_map(self):
        stored = {'old/key': 'https://open.spotify.com/episode/OLD'}
        with patch.dict(os.environ, self._ENV), \
             patch('parlament.mirror.get_json', return_value=dict(stored)), \
             patch('parlament.mirror.put_json') as put, \
             patch('parlament.spotify.get_show_episodes',
                   return_value=[('Sessjoni Plenarja S15E017', 'https://open.spotify.com/episode/A')]):
            result = spotify.update_map(self._STORE)
        expected = dict(stored, **{_PS17_KEY: 'https://open.spotify.com/episode/A'})
        self.assertEqual(result, expected)
        put.assert_called_once_with(spotify.MAP_KEY, expected)

    def test_spotify_failure_keeps_stored_map(self):
        stored = {'old/key': 'u'}
        with patch.dict(os.environ, self._ENV), \
             patch('parlament.mirror.get_json', return_value=dict(stored)), \
             patch('parlament.mirror.put_json') as put, \
             patch('parlament.spotify.get_show_episodes', side_effect=Exception('down')):
            self.assertEqual(spotify.update_map(self._STORE), stored)
        put.assert_not_called()

    def test_without_credentials_keeps_stored_map(self):
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': '', 'SPOTIFY_CLIENT_SECRET': ''}), \
             patch('parlament.mirror.get_json', side_effect=mirror.ObjectNotFound(spotify.MAP_KEY)), \
             patch('parlament.mirror.put_json') as put, \
             patch('parlament.spotify.get_show_episodes') as get:
            self.assertEqual(spotify.update_map(self._STORE), {})
        get.assert_not_called()
        put.assert_not_called()

    def test_unreadable_r2_does_not_raise(self):
        with patch('parlament.mirror.get_json', side_effect=Exception('R2 down')):
            self.assertEqual(spotify.update_map(self._STORE), {})


class TestWriteMap(unittest.TestCase):

    def test_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'map.json')
            spotify.write_map({_PS17_KEY: 'u'}, path)
            with open(path, encoding='utf8') as fp:
                self.assertEqual(json.load(fp),
                                 {'showUrl': spotify.SHOW_URL, 'episodes': {_PS17_KEY: 'u'}})


if __name__ == '__main__':
    unittest.main()
