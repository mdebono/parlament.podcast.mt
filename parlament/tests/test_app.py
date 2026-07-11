import contextlib
import copy
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from lxml import etree

from parlament import app, mirror, catalog

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_AUDIO_170 = '/Audio/15thLeg/Plenary/Plenary%20170%2013-11-2023%201600hrs.mp3'
_AUDIO_171 = '/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3'
_AUDIO_PAC = '/Audio/15thLeg/PAC/PAC%2012%2001-07-2026.mp3'

def _make_sitting(number, iso_date, audio_path):
    return {
        'Number': number,
        'Date': iso_date,
        'Title': 'Sessjoni Plenarja',
        'Url': '/15th-leg/plenary-session/ps-{:03}/'.format(number),
        'Media': [{'IsVideo': False, 'Url': audio_path}],
    }

def _make_leg():
    return {
        'Number': 15,
        'Title': 'Fifteenth Legislature',
        'TitleMT': 'Il-Ħmistax-il Leġiżlatura',
        'Committees': [{'CommitteeType': 'Plenary', 'Sittings': [
            _make_sitting(170, '2023-11-13T16:00:00', _AUDIO_170),
            _make_sitting(171, '2023-11-14T16:00:00', _AUDIO_171),
        ]}],
    }

def _make_committee_meeting():
    return {
        'MeetingTitles': [
            {'Language': 'en', 'Title': 'Public Accounts Committee'},
            {'Language': 'mt', 'Title': 'Kumitat dwar il-Kontijiet Pubbliċi'},
        ],
        'MeetingURL': '/15th-leg/pac/meeting-12/',
        'MeetingNo': '12',
        'MeetingDate': '2026-07-01T14:30:00',
        'IsPlenary': False,
        'IsSitting': True,
        'AudioURLs': [_AUDIO_PAC],
        'VideoURLs': [],
    }

def _make_plenary_meeting():
    """The same sitting 171 as seen by the homepage widget."""
    return {
        'MeetingTitles': [{'Language': 'mt', 'Title': 'Sessjoni Plenarja'}],
        'MeetingURL': '/15th-leg/plenary-session/ps-171/',
        'MeetingNo': '171',
        'MeetingDate': '2023-11-14T16:00:00',
        'IsPlenary': True,
        'IsSitting': True,
        'AudioURLs': [_AUDIO_171],
        'VideoURLs': [],
    }

def _fake_mirror(audio_url, s3_key):
    return mirror.R2_PARLAMENT_URL + '/' + mirror.prep_s3_key(s3_key)

def _empty_page():
    response = MagicMock()
    response.status_code = 200
    response.content = b'<html><body>no agenda</body></html>'
    response.raise_for_status = MagicMock()
    return response

def _read_feed_items(path='podcast.rss'):
    tree = etree.parse(path)
    items = []
    for item in tree.findall('.//channel/item'):
        items.append({
            'title': item.findtext('title'),
            'guid': item.findtext('guid'),
            'enclosure_url': item.find('enclosure').get('url'),
            'enclosure_length': item.find('enclosure').get('length'),
        })
    return items


class TestRun(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmpdir.cleanup()

    def _run(self, stored_catalog=None, leg='default', meetings='default',
             mirror_side_effect=_fake_mirror, put_json_side_effect=None):
        """Run app.run() with every external effect patched. Returns the
        catalogue that was written (or None if put_json never ran)."""
        written = []

        def _capture_put(key, obj):
            if put_json_side_effect is not None:
                raise put_json_side_effect
            written.append(copy.deepcopy(obj))

        if stored_catalog is None:
            get_json_kwargs = {'side_effect': mirror.ObjectNotFound(catalog.CATALOG_KEY)}
        else:
            get_json_kwargs = {'return_value': copy.deepcopy(stored_catalog)}

        leg_kwargs = ({'side_effect': Exception('archive down')} if leg is None
                      else {'return_value': _make_leg() if leg == 'default' else leg})
        meetings_kwargs = ({'side_effect': Exception('homepage down')} if meetings is None
                           else {'return_value': [_make_committee_meeting()] if meetings == 'default' else meetings})

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('parlament.mirror.get_json', **get_json_kwargs))
            stack.enter_context(patch('parlament.mirror.put_json', side_effect=_capture_put))
            stack.enter_context(patch('parlament.mirror.copy_object'))
            stack.enter_context(patch('parlament.mirror.mirror_audio_to_r2',
                                      side_effect=mirror_side_effect))
            stack.enter_context(patch('parlament.mirror.get_r2_content_length',
                                      return_value='999'))
            stack.enter_context(patch('parlament.papi.get_leg', **leg_kwargs))
            stack.enter_context(patch('parlament.latest.get_latest_media', **meetings_kwargs))
            stack.enter_context(patch('parlament.papi.cache.httpGet',
                                      return_value=_empty_page()))
            stack.enter_context(patch('parlament.papi.cache.httpHead'))
            app.run()

        return written[-1] if written else None

    # ------------------------------------------------------------------
    # bootstrap run: archive items keep today's exact titles and guids
    # ------------------------------------------------------------------
    def test_bootstrap_run_backward_compatible(self):
        store = self._run()
        items = _read_feed_items()
        self.assertEqual([i['title'] for i in items], [
            'Kumitat dwar il-Kontijiet Pubbliċi M012',
            'Sessjoni Plenarja S15E171',
            'Sessjoni Plenarja S15E170',
        ])
        # guid must be byte-identical to what the pre-catalogue code
        # published (the R2 URL with the unquoted key)
        self.assertEqual(items[1]['guid'],
            'https://r2.parlament.podcast.mt/Audio/15thLeg/Plenary/Plenary 171 14-11-2023 1600hrs.mp3')
        # feedgenerator percent-encodes the enclosure url attribute (as it
        # always has); the guid keeps the raw form
        self.assertEqual(items[1]['enclosure_url'],
            'https://r2.parlament.podcast.mt/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3')
        self.assertEqual(items[0]['enclosure_length'], '999')
        self.assertEqual(len(store['episodes']), 3)

    # ------------------------------------------------------------------
    # items that rolled off both sources are still published
    # ------------------------------------------------------------------
    def test_rolled_off_items_kept(self):
        store = self._run()
        self._run(stored_catalog=store, leg=None, meetings=None)
        items = _read_feed_items()
        self.assertEqual(len(items), 3)
        self.assertIn('Sessjoni Plenarja S15E171', [i['title'] for i in items])

    # ------------------------------------------------------------------
    # a mirroring failure skips only the failing item
    # ------------------------------------------------------------------
    def test_mirror_failure_skips_only_that_item(self):
        def failing_mirror(audio_url, s3_key):
            if 'PAC' in s3_key:
                raise Exception('upload failed')
            return _fake_mirror(audio_url, s3_key)

        store = self._run(mirror_side_effect=failing_mirror)
        titles = [i['title'] for i in _read_feed_items()]
        self.assertEqual(titles, ['Sessjoni Plenarja S15E171', 'Sessjoni Plenarja S15E170'])
        self.assertEqual(len(store['episodes']), 2)

    # ------------------------------------------------------------------
    # catalogue save failure must not publish a feed
    # ------------------------------------------------------------------
    def test_save_failure_prevents_feed_write(self):
        with self.assertRaises(RuntimeError):
            self._run(put_json_side_effect=RuntimeError('s3 down'))
        self.assertFalse(os.path.exists('podcast.rss'))

    # ------------------------------------------------------------------
    # the same sitting from both sources becomes one episode
    # ------------------------------------------------------------------
    def test_same_item_from_both_sources_deduped(self):
        store = self._run(meetings=[_make_plenary_meeting()])
        titles = [i['title'] for i in _read_feed_items()]
        self.assertEqual(titles, ['Sessjoni Plenarja S15E171', 'Sessjoni Plenarja S15E170'])
        key = mirror.prep_s3_key(_AUDIO_171)
        self.assertEqual(store['episodes'][key]['sources'],
                         ['media-archive', 'latest-media'])

    # ------------------------------------------------------------------
    # nothing to publish at all: fail loudly
    # ------------------------------------------------------------------
    def test_no_sources_and_empty_catalog_raises(self):
        with self.assertRaises(RuntimeError):
            self._run(leg=None, meetings=None)


if __name__ == '__main__':
    unittest.main()
