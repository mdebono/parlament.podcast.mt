import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pytz

from parlament import catalog, mirror

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_MALTA = pytz.timezone('Europe/Malta')

def _make_candidate(**overrides):
    candidate = {
        'source_audio_path': '/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3',
        'kind': 'plenary',
        'title': 'Sessjoni Plenarja S15E171',
        'link': 'https://parlament.mt/15th-leg/plenary-session/ps-171/',
        'pubdate': _MALTA.localize(datetime(2023, 11, 14, 16, 0)),
        'source': 'media-archive',
        'build_texts': lambda: ('description', 'summary'),
    }
    candidate.update(overrides)
    return candidate

def _make_entry(candidate=None, **kwargs):
    if candidate is None:
        candidate = _make_candidate()
    return catalog.make_entry(
        candidate,
        audio_url=kwargs.get('audio_url', 'https://r2.parlament.podcast.mt/Audio/x.mp3'),
        content_length=kwargs.get('content_length', '123'),
        description=kwargs.get('description', 'description'),
        summary=kwargs.get('summary', 'summary'),
        first_seen=kwargs.get('first_seen', datetime(2026, 7, 11, tzinfo=timezone.utc)),
    )


class TestEpisodeKey(unittest.TestCase):

    def test_key_is_unquoted_s3_key(self):
        key = catalog.episode_key(_make_candidate())
        self.assertEqual(key, 'Audio/15thLeg/Plenary/Plenary 171 14-11-2023 1600hrs.mp3')

    def test_encoding_differences_collapse_to_same_key(self):
        encoded = _make_candidate(source_audio_path='/Audio/A%20B.mp3')
        plain = _make_candidate(source_audio_path='/Audio/A B.mp3')
        self.assertEqual(catalog.episode_key(encoded), catalog.episode_key(plain))


class TestLoadCatalog(unittest.TestCase):

    @patch('parlament.mirror.get_json', side_effect=mirror.ObjectNotFound(catalog.CATALOG_KEY))
    def test_missing_catalog_bootstraps_empty(self, mock_get):
        store = catalog.load_catalog()
        self.assertEqual(store, {'version': 1, 'episodes': {}})

    @patch('parlament.mirror.get_json', side_effect=RuntimeError('s3 down'))
    def test_other_errors_propagate(self, mock_get):
        # A transient read failure must never be mistaken for an empty
        # catalogue - that would rebuild history from just the recent items.
        with self.assertRaises(RuntimeError):
            catalog.load_catalog()

    @patch('parlament.mirror.get_json')
    def test_returns_stored_catalog(self, mock_get):
        stored = {'version': 1, 'episodes': {'k': _make_entry()}}
        mock_get.return_value = stored
        self.assertEqual(catalog.load_catalog(), stored)
        mock_get.assert_called_once_with(catalog.CATALOG_KEY)


class TestSaveCatalog(unittest.TestCase):

    @patch('parlament.mirror.put_json')
    @patch('parlament.mirror.copy_object')
    def test_first_save_skips_backup(self, mock_copy, mock_put):
        store = {'version': 1, 'episodes': {'k': _make_entry()}}
        catalog.save_catalog(store, previous_count=0)
        mock_copy.assert_not_called()
        mock_put.assert_called_once_with(catalog.CATALOG_KEY, store)

    @patch('parlament.mirror.put_json')
    @patch('parlament.mirror.copy_object')
    def test_backup_before_overwrite(self, mock_copy, mock_put):
        store = {'version': 1, 'episodes': {'k1': _make_entry(), 'k2': _make_entry()}}
        catalog.save_catalog(store, previous_count=1)
        mock_copy.assert_called_once_with(catalog.CATALOG_KEY, catalog.CATALOG_BACKUP_KEY)
        mock_put.assert_called_once()

    @patch('parlament.mirror.put_json')
    @patch('parlament.mirror.copy_object')
    def test_shrinking_catalog_refused(self, mock_copy, mock_put):
        store = {'version': 1, 'episodes': {'k': _make_entry()}}
        with self.assertRaises(RuntimeError):
            catalog.save_catalog(store, previous_count=2)
        mock_copy.assert_not_called()
        mock_put.assert_not_called()


class TestMakeEntry(unittest.TestCase):

    def test_entry_has_all_fields(self):
        entry = _make_entry()
        self.assertEqual(entry, {
            'guid': 'https://r2.parlament.podcast.mt/Audio/x.mp3',
            'title': 'Sessjoni Plenarja S15E171',
            'description': 'description',
            'summary': 'summary',
            'link': 'https://parlament.mt/15th-leg/plenary-session/ps-171/',
            'audio_url': 'https://r2.parlament.podcast.mt/Audio/x.mp3',
            'content_length': '123',
            'pubdate': '2023-11-14T16:00:00+01:00',
            'kind': 'plenary',
            'sources': ['media-archive'],
            'source_audio_path': '/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3',
            'first_seen': '2026-07-11T00:00:00+00:00',
        })


class TestUpdateExisting(unittest.TestCase):

    def test_new_source_unioned(self):
        entry = _make_entry()
        catalog.update_existing(entry, _make_candidate(source='latest-media'))
        self.assertEqual(entry['sources'], ['media-archive', 'latest-media'])

    def test_same_source_not_duplicated(self):
        entry = _make_entry()
        catalog.update_existing(entry, _make_candidate())
        self.assertEqual(entry['sources'], ['media-archive'])

    def test_published_metadata_never_mutates(self):
        entry = _make_entry()
        catalog.update_existing(entry, _make_candidate(
            source='latest-media',
            title='A Different Title',
            link='https://parlament.mt/other',
            pubdate=_MALTA.localize(datetime(2024, 1, 1)),
        ))
        self.assertEqual(entry['title'], 'Sessjoni Plenarja S15E171')
        self.assertEqual(entry['link'], 'https://parlament.mt/15th-leg/plenary-session/ps-171/')
        self.assertEqual(entry['pubdate'], '2023-11-14T16:00:00+01:00')


class TestUpdateTexts(unittest.TestCase):

    def test_only_description_and_summary_change(self):
        entry = _make_entry()
        before = dict(entry)
        catalog.update_texts(entry, 'A rebuilt description', 'A rebuilt summary')
        self.assertEqual(entry['description'], 'A rebuilt description')
        self.assertEqual(entry['summary'], 'A rebuilt summary')
        for field in ('guid', 'title', 'link', 'audio_url', 'content_length',
                      'pubdate', 'kind', 'sources', 'source_audio_path', 'first_seen'):
            self.assertEqual(entry[field], before[field], field)


class TestSortedEntries(unittest.TestCase):

    def test_newest_first(self):
        old = _make_candidate(pubdate=_MALTA.localize(datetime(2023, 1, 1)), title='old')
        new = _make_candidate(pubdate=_MALTA.localize(datetime(2024, 1, 1)), title='new')
        store = catalog.new_catalog()
        catalog.add_episode(store, 'a', catalog.make_entry(old, 'u1', '', 'd', 's'))
        catalog.add_episode(store, 'b', catalog.make_entry(new, 'u2', '', 'd', 's'))
        titles = [entry['title'] for entry in catalog.sorted_entries(store)]
        self.assertEqual(titles, ['new', 'old'])


if __name__ == '__main__':
    unittest.main()
