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

def _make_leg_with_committee():
    """The same legislature as _make_leg, plus a non-Plenary committee -
    the archive carries every CommitteeType's full sitting history, not
    just Plenary."""
    leg = _make_leg()
    leg['Committees'].append({'CommitteeType': 'Public Accounts Committee', 'Sittings': [
        {
            'Number': 12,
            'Date': '2026-07-01T14:30:00',
            'Title': 'Kumitat dwar il-Kontijiet Pubbliċi',
            'Url': '/15th-leg/pac/meeting-12/',
            'Media': [{'IsVideo': False, 'Url': _AUDIO_PAC}],
        },
    ]})
    return leg

def _fake_mirror(audio_url, s3_key):
    return mirror.R2_PARLAMENT_URL + '/' + mirror.prep_s3_key(s3_key)

def _page(content):
    response = MagicMock()
    response.status_code = 200
    response.content = content
    response.raise_for_status = MagicMock()
    return response

def _empty_page():
    return _page(b'<html><body>no agenda</body></html>')

_COMMITTEE_AGENDA_HTML = (
    b'<html><body><div id="orders">'
    b'<p>1. Confirmation of Minutes;</p>'
    b'<p>2. House Business; and</p>'
    b'</div></body></html>'
)

_ITUNES_NS = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'

def _read_feed_items(path='podcast.rss'):
    tree = etree.parse(path)
    items = []
    for item in tree.findall('.//channel/item'):
        items.append({
            'title': item.findtext('title'),
            'guid': item.findtext('guid'),
            'description': item.findtext('description'),
            'summary': item.findtext(_ITUNES_NS + 'summary'),
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
             mirror_side_effect=_fake_mirror, put_json_side_effect=None,
             force_backfill=False, agenda_page=None):
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
                                      return_value=agenda_page or _empty_page()))
            stack.enter_context(patch('parlament.papi.cache.httpHead'))
            if force_backfill:
                stack.enter_context(patch.dict(os.environ, {'FORCE_BACKFILL': 'true'}))
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
    # descriptions are HTML, with a plain-text itunes:summary alongside
    # ------------------------------------------------------------------
    def test_descriptions_are_html_with_plain_summary(self):
        self._run()
        items = _read_feed_items()
        plenary = next(i for i in items if 'S15E171' in i['title'])
        self.assertTrue(plenary['description'].startswith('<p>Il-Ħmistax-il Leġiżlatura Seduta Nru: 171'))
        self.assertNotIn('<p>', plenary['summary'])
        self.assertTrue(plenary['summary'].startswith('Il-Ħmistax-il Leġiżlatura Seduta Nru: 171'))

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

    # ------------------------------------------------------------------
    # FORCE_BACKFILL repairs a stale committee description (e.g. one
    # ingested before the agenda-parser fix) using the full archive, once
    # the widget has rolled off - without touching its identity fields
    # ------------------------------------------------------------------
    def test_force_backfill_repairs_stale_committee_description(self):
        store = self._run()  # bootstrap: PAC entry has no agenda (empty page)
        pac_key = mirror.prep_s3_key(_AUDIO_PAC)
        before = copy.deepcopy(store['episodes'][pac_key])
        self.assertNotIn('Aġenda', before['description'])

        store = self._run(
            stored_catalog=store,
            leg=_make_leg_with_committee(),
            meetings=None,  # widget rolled off; only the archive can help now
            force_backfill=True,
            agenda_page=_page(_COMMITTEE_AGENDA_HTML),
        )

        after = store['episodes'][pac_key]
        self.assertIn('Aġenda', after['description'])
        self.assertIn('<ol><li>Confirmation of Minutes;</li>', after['description'])
        self.assertIn('Aġenda', after['summary'])
        self.assertIn('- 1. Confirmation of Minutes;', after['summary'])
        self.assertNotIn('<', after['summary'])
        for field in ('guid', 'title', 'link', 'pubdate', 'kind', 'sources'):
            self.assertEqual(after[field], before[field], field)

    # ------------------------------------------------------------------
    # without the flag, nothing is rebuilt even though the archive could
    # ------------------------------------------------------------------
    def test_without_force_backfill_stale_description_untouched(self):
        store = self._run()
        pac_key = mirror.prep_s3_key(_AUDIO_PAC)

        store = self._run(
            stored_catalog=store,
            leg=_make_leg_with_committee(),
            meetings=None,
            force_backfill=False,
            agenda_page=_page(_COMMITTEE_AGENDA_HTML),
        )

        self.assertNotIn('Aġenda', store['episodes'][pac_key]['description'])


class TestArchiveSittingIndex(unittest.TestCase):

    def test_indexes_every_committee_type(self):
        index = app.archive_sitting_index(_make_leg_with_committee())
        self.assertEqual(set(index.keys()), {
            mirror.prep_s3_key(_AUDIO_170),
            mirror.prep_s3_key(_AUDIO_171),
            mirror.prep_s3_key(_AUDIO_PAC),
        })
        self.assertEqual(index[mirror.prep_s3_key(_AUDIO_PAC)]['Number'], 12)

    def test_sitting_without_audio_skipped(self):
        leg = _make_leg_with_committee()
        leg['Committees'][0]['Sittings'].append({
            'Number': 999, 'Date': '2023-01-01T10:00:00', 'Title': 'No audio',
            'Url': '/x/', 'Media': [],
        })
        index = app.archive_sitting_index(leg)
        numbers = [sitting['Number'] for sitting in index.values()]
        self.assertNotIn(999, numbers)


class TestBackfillDescriptions(unittest.TestCase):

    def _store_with_entry(self, kind, key, description='stale'):
        store = catalog.new_catalog()
        store['episodes'][key] = {
            'guid': 'g', 'title': 't', 'description': description, 'link': 'l',
            'audio_url': 'a', 'content_length': '1', 'pubdate': '2023-01-01T00:00:00+00:00',
            'kind': kind, 'sources': ['media-archive'], 'source_audio_path': '/x',
            'first_seen': '2023-01-01T00:00:00+00:00',
        }
        return store

    @patch('parlament.papi.cache.httpGet', return_value=_page(_COMMITTEE_AGENDA_HTML))
    def test_matched_committee_entry_rebuilt(self, mock_get):
        key = mirror.prep_s3_key(_AUDIO_PAC)
        store = self._store_with_entry('committee', key)
        app.backfill_descriptions(store, _make_leg_with_committee())
        entry = store['episodes'][key]
        self.assertIn('Kumitat dwar il-Kontijiet Pubbliċi Laqgħa Nru: 012', entry['description'])
        self.assertIn('Aġenda', entry['description'])
        self.assertIn('Aġenda', entry['summary'])
        link = 'https://parlament.mt/mt/15th-leg/pac/meeting-12/'
        self.assertIn('Aktar informazzjoni: <a href="{0}">{0}</a>'.format(link), entry['description'])
        self.assertIn('Aktar informazzjoni: ' + link, entry['summary'])

    @patch('parlament.papi.cache.httpGet', return_value=_empty_page())
    def test_matched_plenary_entry_uses_legislature_title(self, mock_get):
        # Regression test: backfill must use the legislature's title for
        # plenary (matching the live path via get_episode_texts), not the
        # sitting's own title ("Sessjoni Plenarja" for every sitting) -
        # those are different strings and must not be confused.
        key = mirror.prep_s3_key(_AUDIO_171)
        store = self._store_with_entry('plenary', key)
        app.backfill_descriptions(store, _make_leg())
        entry = store['episodes'][key]
        self.assertTrue(entry['description'].startswith('<p>Il-Ħmistax-il Leġiżlatura Seduta Nru: 171'))
        self.assertTrue(entry['summary'].startswith('Il-Ħmistax-il Leġiżlatura Seduta Nru: 171'))
        self.assertNotIn('Sessjoni Plenarja Seduta Nru', entry['description'])

    @patch('parlament.papi.cache.httpGet', return_value=_page(b'<html><body>x</body></html>'))
    def test_unmatched_entry_untouched(self, mock_get):
        store = self._store_with_entry('committee', 'no-such-key')
        app.backfill_descriptions(store, _make_leg_with_committee())
        self.assertEqual(store['episodes']['no-such-key']['description'], 'stale')

    def test_event_kind_never_matched(self):
        key = mirror.prep_s3_key(_AUDIO_PAC)
        store = self._store_with_entry('event', key)
        app.backfill_descriptions(store, _make_leg_with_committee())
        self.assertEqual(store['episodes'][key]['description'], 'stale')

    def test_agenda_fetch_failure_leaves_entry_untouched_others_still_backfilled(self):
        # A transient agenda-fetch failure for one entry must not overwrite
        # its existing (possibly already-good) description with an
        # agenda-less one, and must not stop other entries from being
        # backfilled in the same run.
        pac_key = mirror.prep_s3_key(_AUDIO_PAC)
        plenary_key = mirror.prep_s3_key(_AUDIO_171)
        store = self._store_with_entry('committee', pac_key, description='stale-pac')
        store['episodes'][plenary_key] = {
            'guid': 'g2', 'title': 't2', 'description': 'stale-plenary', 'link': 'l2',
            'audio_url': 'a2', 'content_length': '1', 'pubdate': '2023-01-01T00:00:00+00:00',
            'kind': 'plenary', 'sources': ['media-archive'], 'source_audio_path': '/y',
            'first_seen': '2023-01-01T00:00:00+00:00',
        }

        def fake_get(url, referer=None):
            if 'pac' in url:
                raise Exception('simulated fetch failure')
            return _empty_page()

        with patch('parlament.papi.cache.httpGet', side_effect=fake_get):
            app.backfill_descriptions(store, _make_leg_with_committee())

        self.assertEqual(store['episodes'][pac_key]['description'], 'stale-pac')
        self.assertNotEqual(store['episodes'][plenary_key]['description'], 'stale-plenary')
        self.assertIn('Il-Ħmistax-il Leġiżlatura Seduta Nru: 171',
                       store['episodes'][plenary_key]['description'])

    def test_malformed_sitting_leaves_entry_untouched_others_still_backfilled(self):
        # A non-agenda failure (missing/malformed archive field) must be
        # just as harmless to the failed entry and to the rest of the run
        # as an agenda-fetch failure.
        pac_key = mirror.prep_s3_key(_AUDIO_PAC)
        plenary_key = mirror.prep_s3_key(_AUDIO_171)
        store = self._store_with_entry('committee', pac_key, description='stale-pac')
        store['episodes'][plenary_key] = {
            'guid': 'g2', 'title': 't2', 'description': 'stale-plenary', 'link': 'l2',
            'audio_url': 'a2', 'content_length': '1', 'pubdate': '2023-01-01T00:00:00+00:00',
            'kind': 'plenary', 'sources': ['media-archive'], 'source_audio_path': '/y',
            'first_seen': '2023-01-01T00:00:00+00:00',
        }
        leg = _make_leg_with_committee()
        del leg['Committees'][1]['Sittings'][0]['Date']  # malformed: get_sitting_date will KeyError

        with patch('parlament.papi.cache.httpGet', return_value=_empty_page()):
            app.backfill_descriptions(store, leg)

        self.assertEqual(store['episodes'][pac_key]['description'], 'stale-pac')
        self.assertNotEqual(store['episodes'][plenary_key]['description'], 'stale-plenary')
        self.assertIn('Il-Ħmistax-il Leġiżlatura Seduta Nru: 171',
                       store['episodes'][plenary_key]['description'])


if __name__ == '__main__':
    unittest.main()
