import re
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytz

from parlament import papi

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


# Use only the path, not the domain, to match how correct_audio_url constructs new_url
_BASE = '/Audio/15thLeg/Plenary/'
_WRONG_URL = _BASE + 'Plenary%20172%2015-11-2023%200900hrs.mp3'   # episode 172
_RIGHT_URL  = _BASE + 'Plenary%20171%2014-11-2023%201600hrs.mp3'  # episode 171

def _make_sitting(number, iso_date):
    """Return a minimal sitting dict understood by papi helpers."""
    return {
        'Number': number,
        'Date': iso_date,
        'Title': 'Sessjoni Plenarja',
        'Url': '/test',
        'Media': [],
    }

def _head_response(status_code):
    r = MagicMock()
    r.status_code = status_code
    return r


class TestParlamentApi(unittest.TestCase):

    def test_get_title(self):
        sitting = {'Title': 'This is a title'}
        title = papi.get_sitting_title(sitting)
        self.assertEqual(title, 'This is a title')


class TestCorrectAudioUrl(unittest.TestCase):

    def _sitting171(self):
        # 14 Nov 2023 16:00 Malta local time
        return _make_sitting(171, '2023-11-14T16:00:00')

    # ------------------------------------------------------------------
    # episode numbers already match – no HEAD request should be made
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead')
    def test_already_correct_no_head(self, mock_head):
        sitting = self._sitting171()
        url = _BASE + 'Plenary%20171%2014-11-2023%201600hrs.mp3'
        result = papi.correct_audio_url(sitting, url)
        self.assertEqual(result, url)
        mock_head.assert_not_called()

    # ------------------------------------------------------------------
    # mismatch + HEAD 200 → corrected URL returned
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead', return_value=_head_response(200))
    def test_mismatch_head_200_returns_corrected(self, mock_head):
        sitting = self._sitting171()
        result = papi.correct_audio_url(sitting, _WRONG_URL)
        self.assertEqual(result, _RIGHT_URL)
        mock_head.assert_called_once_with(papi.PARLAMENT_URL + _RIGHT_URL)

    # ------------------------------------------------------------------
    # mismatch + HEAD 404 → original URL kept
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead', return_value=_head_response(404))
    def test_mismatch_head_404_returns_original(self, mock_head):
        sitting = self._sitting171()
        result = papi.correct_audio_url(sitting, _WRONG_URL)
        self.assertEqual(result, _WRONG_URL)

    # ------------------------------------------------------------------
    # mismatch + HEAD raises exception → original URL kept
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead', side_effect=Exception('timeout'))
    def test_mismatch_head_exception_returns_original(self, mock_head):
        sitting = self._sitting171()
        result = papi.correct_audio_url(sitting, _WRONG_URL)
        self.assertEqual(result, _WRONG_URL)

    # ------------------------------------------------------------------
    # unrecognised URL format → returned unchanged, no HEAD
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead')
    def test_unrecognised_url_unchanged(self, mock_head):
        sitting = self._sitting171()
        url = '/Audio/custom_format.mp3'
        result = papi.correct_audio_url(sitting, url)
        self.assertEqual(result, url)
        mock_head.assert_not_called()

    # ------------------------------------------------------------------
    # double-space in URL (Plenary%20%20270) → parsed and corrected
    # ------------------------------------------------------------------
    @patch('parlament.papi.cache.httpHead', return_value=_head_response(200))
    def test_double_space_mismatch_corrected(self, mock_head):
        # URL has Plenary%20%20270 (extra space) and wrong episode number
        double_space_url = _BASE + 'Plenary%20%20272%2030-10-2024%201600hrs.mp3'
        sitting = _make_sitting(270, '2024-10-30T16:00:00')
        # corrected URL must preserve the double space
        expected = _BASE + 'Plenary%20%20270%2030-10-2024%201600hrs.mp3'
        result = papi.correct_audio_url(sitting, double_space_url)
        self.assertEqual(result, expected)
        mock_head.assert_called_once_with(papi.PARLAMENT_URL + expected)

    @patch('parlament.papi.cache.httpHead')
    def test_double_space_already_correct_episode_no_head(self, mock_head):
        # Episode number matches despite the double space – no HEAD needed
        double_space_url = _BASE + 'Plenary%20%20270%2030-10-2024%201600hrs.mp3'
        sitting = _make_sitting(270, '2024-10-30T16:00:00')
        result = papi.correct_audio_url(sitting, double_space_url)
        self.assertEqual(result, double_space_url)
        mock_head.assert_not_called()


class TestGetPlenarySittings(unittest.TestCase):

    def test_no_plenary_committee_raises(self):
        leg = {'Committees': [{'CommitteeType': 'Budget', 'Sittings': []}]}
        with self.assertRaises(ValueError, msg='Expected ValueError when no plenary committee exists'):
            papi.get_plenary_sittings(leg)

    def test_returns_sittings_for_plenary(self):
        sittings = [_make_sitting(1, '2023-01-01T10:00:00')]
        leg = {'Committees': [{'CommitteeType': 'Plenary', 'Sittings': sittings}]}
        result = papi.get_plenary_sittings(leg)
        self.assertEqual(result, sittings)


_AGENDA_HTML = '''
<html><head><meta charset="utf-8" /></head><body>
<div class="panel-body" id="orders">
  <div class="row"><div class="col-md-12 container">
    <p style="font-weight:bold">MOZZJONIJIET</p>
    <table class="table table-striped">
      <tr><td><a href="/mt/15th-leg/motions/motion-no-015/">Mozzjoni Nru 15 - Xi Haga</a></td></tr>
    </table>
    <p style="font-weight:bold">ORDNIJIET TAL-ĠURNATA</p>
    <table class="table table-striped">
      <tr><td><div><p>Indirizz b'risposta</p></div></td></tr>
      <tr><td><a href="/mt/15th-leg/bills/bill-005/">Abbozz Nru  5 - Xi Haga

 -  L-Ewwel Qari
      </a><br /></td></tr>
    </table>
  </div></div>
</div>
</body></html>
'''.encode('utf-8')

_NO_AGENDA_HTML = b'<html><body><div class="panel-body">no orders here</div></body></html>'

# Mirrors the opening/constitutive sitting, which packs several ceremonial
# steps into a single <tr> using <p> and <br> instead of separate rows: one
# mid-sentence <br> wrap (no punctuation before the break) that must be
# rejoined, and several <br>-separated sentences that must stay separate.
_PACKED_ROW_HTML = '''
<html><head><meta charset="utf-8" /></head><body>
<div class="panel-body" id="orders">
  <div class="row"><div class="col-md-12 container">
    <p style="font-weight:bold">ORDNIJIET TAL-ĠURNATA</p>
    <table class="table table-striped">
      <tr><td><div>
        <p>Bidu tas-Seduta Parlamentari.</p>
        <p>L-Iskrivan taqra r-riżultati u<br>l-ismijiet tal-Membri eletti.</p>
        <p>Elezzjoni ta' Deputy Speaker.<br>L-Onorevoli Membri jieħdu l-Ġurament.<br>Il-Kamra tiġi aġġornata.</p>
      </div></td></tr>
    </table>
  </div></div>
</div>
</body></html>
'''.encode('utf-8')


# Committee meeting pages render the agenda as plain (non-bold) <p>
# elements with no table at all - captured from a live House Business
# Committee page (HBC 002, 07-Jul-2026).
_COMMITTEE_AGENDA_HTML = '''
<html><head><meta charset="utf-8" /></head><body>
<div class="panel-body" id="orders">
    <div class="row">
        <div class="col-md-12 container">
            <p>1. Confirmation of Minutes;</p>
            <p>2. House Business; and</p>
            <p>3. Other Matters</p>
        </div>
    </div>
</div>
</body></html>
'''.encode('utf-8')

# The Maltese version of the same committee page (HBC 002) packs all three
# items into a single <p> separated by <br /> instead of three separate
# <p> elements - captured live after a production episode's agenda came
# through as one run-on line with no separators at all.
_COMMITTEE_AGENDA_HTML_BR_PACKED = '''
<html><head><meta charset="utf-8" /></head><body>
<div class="panel-body" id="orders">
    <div class="row">
        <div class="col-md-12 container">
            <p>1. Konferma tal-Minuti;<br />2. Xogħol tal-Kamra; u<br />3. Affarijiet oħra</p>
        </div>
    </div>
</div>
</body></html>
'''.encode('utf-8')


class TestParseAgendaHtml(unittest.TestCase):

    def test_parses_committee_plain_paragraph_items(self):
        agenda = papi.parse_agenda_html(_COMMITTEE_AGENDA_HTML)
        self.assertEqual(agenda,
            '- 1. Confirmation of Minutes;\n'
            '- 2. House Business; and\n'
            '- 3. Other Matters')

    def test_parses_br_packed_committee_items(self):
        # Items enumerated "1. Foo;<br />2. Bar; u<br />3. Baz" inside a
        # single <p> - a real production episode's agenda came through as
        # one run-on line with no separator at all before this was fixed.
        agenda = papi.parse_agenda_html(_COMMITTEE_AGENDA_HTML_BR_PACKED)
        self.assertEqual(agenda,
            '- 1. Konferma tal-Minuti;\n'
            '- 2. Xogħol tal-Kamra; u\n'
            '- 3. Affarijiet oħra')

    def test_parses_headings_and_items(self):
        agenda = papi.parse_agenda_html(_AGENDA_HTML)
        self.assertEqual(agenda,
            'MOZZJONIJIET\n'
            '- Mozzjoni Nru 15 - Xi Haga\n'
            'ORDNIJIET TAL-ĠURNATA\n'
            "- Indirizz b'risposta\n"
            '- Abbozz Nru 5 - Xi Haga - L-Ewwel Qari')

    def test_no_orders_div_returns_none(self):
        self.assertIsNone(papi.parse_agenda_html(_NO_AGENDA_HTML))

    def test_empty_orders_div_returns_none(self):
        self.assertIsNone(papi.parse_agenda_html(b'<html><body><div id="orders"></div></body></html>'))

    def test_packed_row_splits_into_separate_steps(self):
        agenda = papi.parse_agenda_html(_PACKED_ROW_HTML)
        self.assertEqual(agenda,
            'ORDNIJIET TAL-ĠURNATA\n'
            '- Bidu tas-Seduta Parlamentari.\n'
            '- L-Iskrivan taqra r-riżultati u l-ismijiet tal-Membri eletti.\n'
            "- Elezzjoni ta' Deputy Speaker.\n"
            "- L-Onorevoli Membri jieħdu l-Ġurament.\n"
            '- Il-Kamra tiġi aġġornata.')

    def test_stray_plain_paragraph_ignored_on_table_based_page(self):
        # A plenary-style page (has a table) with an incidental non-bold
        # <p> outside the table - must be ignored, not treated as a
        # committee-style agenda item.
        html = '''
        <html><head><meta charset="utf-8" /></head><body>
        <div id="orders">
            <p>This session was rescheduled from last week.</p>
            <p style="font-weight:bold">ORDNIJIET TAL-ĠURNATA</p>
            <table><tr><td>Abbozz Nru 5 - Xi Haga</td></tr></table>
        </div>
        </body></html>
        '''.encode('utf-8')
        agenda = papi.parse_agenda_html(html)
        self.assertEqual(agenda,
            'ORDNIJIET TAL-ĠURNATA\n'
            '- Abbozz Nru 5 - Xi Haga')


class TestGetSittingUrlMt(unittest.TestCase):

    def test_language_neutral_url_gets_mt_prefix(self):
        sitting = {'Url': '/15th-leg/plenary-session/ps-001/'}
        self.assertEqual(papi.get_sitting_url_mt(sitting),
                         papi.PARLAMENT_URL + '/mt/15th-leg/plenary-session/ps-001/')

    def test_en_url_is_switched_to_mt(self):
        sitting = {'Url': '/en/15th-leg/plenary-session/ps-001/'}
        self.assertEqual(papi.get_sitting_url_mt(sitting),
                         papi.PARLAMENT_URL + '/mt/15th-leg/plenary-session/ps-001/')

    def test_mt_url_is_unchanged(self):
        sitting = {'Url': '/mt/15th-leg/plenary-session/ps-001/'}
        self.assertEqual(papi.get_sitting_url_mt(sitting),
                         papi.PARLAMENT_URL + '/mt/15th-leg/plenary-session/ps-001/')


def _page_response(content, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.raise_for_status = MagicMock()
    return r


class TestGetEpisodeTexts(unittest.TestCase):

    _LEG = {'TitleMT': 'Il-Hmistax-il Legislatura', 'Number': 15}

    def _sitting(self):
        return _make_sitting(1, '2025-06-30T16:00:00')

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_AGENDA_HTML))
    def test_texts_include_agenda(self, mock_get):
        html, summary = papi.get_episode_texts(self._LEG, self._sitting())
        self.assertIn('Il-Hmistax-il Legislatura Seduta Nru: 001', summary)
        self.assertIn('\n\nAġenda:\nMOZZJONIJIET\n', summary)
        self.assertIn('- Mozzjoni Nru 15 - Xi Haga', summary)
        self.assertIn('<p>Il-Hmistax-il Legislatura Seduta Nru: 001', html)
        self.assertIn('<p><strong>Aġenda:</strong></p>', html)
        self.assertIn('<p><strong>MOZZJONIJIET</strong></p>', html)
        self.assertIn('<li>Mozzjoni Nru 15 - Xi Haga</li>', html)
        mock_get.assert_called_once_with(papi.PARLAMENT_URL + '/mt/test', referer=papi.PARLAMENT_URL)

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_NO_AGENDA_HTML))
    def test_texts_without_agenda_unchanged(self, mock_get):
        html, summary = papi.get_episode_texts(self._LEG, self._sitting())
        self.assertNotIn('Aġenda', summary)
        self.assertNotIn('Aġenda', html)
        self.assertTrue(summary.startswith('Il-Hmistax-il Legislatura Seduta Nru: 001'))
        link = papi.PARLAMENT_URL + '/mt/test'
        self.assertIn('\n\nAktar informazzjoni: ' + link, summary)
        self.assertIn('<p>Aktar informazzjoni: <a href="{0}">{0}</a></p>'.format(link), html)

    @patch('parlament.papi.cache.httpGet', side_effect=Exception('timeout'))
    def test_texts_survive_fetch_failure(self, mock_get):
        html, summary = papi.get_episode_texts(self._LEG, self._sitting())
        self.assertNotIn('Aġenda', summary)
        self.assertIn('Seduta Nru: 001', summary)


_AGENDA_LINES = [('heading', 'MOZZJONIJIET'), ('item', 'Xi Haga')]


class TestLinesToHtml(unittest.TestCase):

    def test_numbered_items_become_ordered_list_with_number_stripped(self):
        lines = [('item', '1. Confirmation of Minutes;'),
                 ('item', '2. House Business; and'),
                 ('item', '3. Other Matters')]
        self.assertEqual(papi.lines_to_html(lines),
            '<ol><li>Confirmation of Minutes;</li>\n'
            '<li>House Business; and</li>\n'
            '<li>Other Matters</li></ol>')

    def test_unnumbered_items_stay_unordered_list_text_unchanged(self):
        lines = [('item', 'Mozzjoni Nru 15 - Xi Haga'), ('item', "Indirizz b'risposta")]
        self.assertEqual(papi.lines_to_html(lines),
            '<ul><li>Mozzjoni Nru 15 - Xi Haga</li>\n'
            "<li>Indirizz b'risposta</li></ul>")

    def test_mixed_numbered_and_unnumbered_run_stays_unordered(self):
        # Only switch to <ol> when every item in the run is numbered - a
        # mixed run keeps the full original text in a <ul>.
        lines = [('item', '1. Numbered'), ('item', 'Not numbered')]
        self.assertEqual(papi.lines_to_html(lines),
            '<ul><li>1. Numbered</li>\n<li>Not numbered</li></ul>')

    def test_numbered_items_in_separate_heading_groups_each_own_ol(self):
        lines = [('heading', 'A'), ('item', '1. First'), ('item', '2. Second'),
                 ('heading', 'B'), ('item', 'Plain')]
        self.assertEqual(papi.lines_to_html(lines),
            '<p><strong>A</strong></p>\n<ol><li>First</li>\n<li>Second</li></ol>\n'
            '<p><strong>B</strong></p>\n<ul><li>Plain</li></ul>')

    def test_tags_stripped_leaves_readable_whitespace(self):
        # The actual failure mode this protects against: a naive preview
        # renderer that deletes markup without inserting a separator at
        # the boundary, which used to run adjacent blocks together with
        # no space at all.
        lines = [('heading', 'ORDNIJIET TAL-ĠURNATA'),
                 ('item', 'Abbozz Nru 2 - Xi Haga'), ('item', 'Abbozz Nru 1 - Ohra')]
        html = papi.lines_to_html(lines)
        stripped = re.sub(r'<[^>]+>', '', html)
        self.assertEqual(stripped,
            'ORDNIJIET TAL-ĠURNATA\nAbbozz Nru 2 - Xi Haga\nAbbozz Nru 1 - Ohra')


_LINK = 'https://parlament.mt/mt/test-link'


class TestBuildSittingTexts(unittest.TestCase):

    _DATE = pytz.timezone('Europe/Malta').localize(datetime(2025, 6, 30, 16, 0))

    def test_plenary_label(self):
        html, summary = papi.build_sitting_texts(
            'Seduta', 'Il-Hmistax-il Legislatura', 1, self._DATE, None, _LINK)
        self.assertTrue(summary.startswith('Il-Hmistax-il Legislatura Seduta Nru: 001'))
        self.assertNotIn('Aġenda', summary)
        self.assertIn('\n\nAktar informazzjoni: ' + _LINK, summary)
        self.assertIn('<p>Aktar informazzjoni: <a href="{0}">{0}</a></p>'.format(_LINK), html)

    def test_committee_label(self):
        html, summary = papi.build_sitting_texts(
            'Laqgħa', 'Kumitat dwar il-Kontijiet Pubbliċi', 12, self._DATE, None, _LINK)
        self.assertTrue(summary.startswith('Kumitat dwar il-Kontijiet Pubbliċi Laqgħa Nru: 012'))

    def test_agenda_appended_when_present(self):
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, _AGENDA_LINES, _LINK)
        self.assertIn('\n\nAġenda:\nMOZZJONIJIET\n- Xi Haga', summary)
        self.assertIn('<p><strong>Aġenda:</strong></p>\n<p><strong>MOZZJONIJIET</strong></p>\n<ul><li>Xi Haga</li></ul>', html)

    def test_agenda_omitted_when_none(self):
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, None, _LINK)
        self.assertNotIn('Aġenda', summary)
        self.assertNotIn('Aġenda', html)

    def test_no_label_uses_plain_title_date_preamble(self):
        # Used for events and committees without a meeting number - no
        # meaningful "Nru:" to show, and number is ignored.
        html, summary = papi.build_sitting_texts(None, 'Konferenza dwar X', None, self._DATE, None, _LINK)
        self.assertTrue(summary.startswith('Konferenza dwar X - '))
        self.assertNotIn('Nru:', summary)
        self.assertIn('\n\nAktar informazzjoni: ' + _LINK, summary)
        self.assertIn('<p>Aktar informazzjoni: <a href="{0}">{0}</a></p>'.format(_LINK), html)

    def test_no_label_still_appends_agenda(self):
        html, summary = papi.build_sitting_texts(None, 'Title', None, self._DATE, _AGENDA_LINES, _LINK)
        self.assertIn('\n\nAġenda:\nMOZZJONIJIET\n- Xi Haga', summary)
        self.assertIn('<p><strong>Aġenda:</strong></p>', html)

    def test_title_html_escaped_but_summary_stays_plain(self):
        html, summary = papi.build_sitting_texts('Seduta', 'R&D <Committee>', 1, self._DATE, None, _LINK)
        self.assertIn('R&D <Committee>', summary)
        self.assertIn('R&amp;D &lt;Committee&gt;', html)
        self.assertNotIn('<Committee>', html)

    def test_agenda_text_html_escaped_but_summary_stays_plain(self):
        lines = [('heading', 'A & B'), ('item', 'Bill <2024>')]
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, lines, _LINK)
        self.assertIn('A & B', summary)
        self.assertIn('Bill <2024>', summary)
        self.assertIn('A &amp; B', html)
        self.assertIn('Bill &lt;2024&gt;', html)

    def test_link_appended_at_bottom_of_both_forms(self):
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, _AGENDA_LINES, _LINK)
        self.assertTrue(summary.endswith('Aktar informazzjoni: ' + _LINK))
        self.assertTrue(html.endswith(
            '<p>Aktar informazzjoni: <a href="{0}">{0}</a></p>'.format(_LINK)))

    def test_link_survives_tag_stripping(self):
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, _AGENDA_LINES, _LINK)
        stripped = re.sub(r'<[^>]+>', '', html)
        self.assertIn('\nAktar informazzjoni: ' + _LINK, stripped)

    def test_link_href_is_quote_escaped(self):
        link = 'https://parlament.mt/mt/weird"page'
        html, summary = papi.build_sitting_texts('Seduta', 'Title', 1, self._DATE, None, link)
        self.assertIn('href="https://parlament.mt/mt/weird&quot;page"', html)


class TestLabelAndTitleForSitting(unittest.TestCase):

    _LEG = {'TitleMT': 'Il-Hmistax-il Legislatura', 'Number': 15}

    def test_plenary_uses_legislature_title(self):
        sitting = _make_sitting(171, '2023-11-14T16:00:00')
        label, title = papi.label_and_title_for_sitting('plenary', self._LEG, sitting)
        self.assertEqual(label, 'Seduta')
        self.assertEqual(title, 'Il-Hmistax-il Legislatura')

    def test_committee_uses_sitting_title(self):
        sitting = _make_sitting(12, '2026-07-01T14:30:00')
        sitting['Title'] = 'Kumitat dwar il-Kontijiet Pubbliċi'
        label, title = papi.label_and_title_for_sitting('committee', self._LEG, sitting)
        self.assertEqual(label, 'Laqgħa')
        self.assertEqual(title, 'Kumitat dwar il-Kontijiet Pubbliċi')

    def test_unknown_kind_returns_none(self):
        sitting = _make_sitting(1, '2023-01-01T10:00:00')
        self.assertEqual(papi.label_and_title_for_sitting('event', self._LEG, sitting), (None, None))


class TestPathToMtUrl(unittest.TestCase):

    def test_language_neutral_path(self):
        self.assertEqual(papi.path_to_mt_url('/15th-leg/pac/meeting-12/'),
                         papi.PARLAMENT_URL + '/mt/15th-leg/pac/meeting-12/')

    def test_en_path_switched_to_mt(self):
        self.assertEqual(papi.path_to_mt_url('/en/15th-leg/pac/meeting-12/'),
                         papi.PARLAMENT_URL + '/mt/15th-leg/pac/meeting-12/')


class TestGetAgendaLinesByUrl(unittest.TestCase):

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_AGENDA_HTML))
    def test_returns_agenda_lines(self, mock_get):
        lines = papi.get_agenda_lines_by_url('https://parlament.mt/mt/test')
        self.assertIn(('heading', 'MOZZJONIJIET'), lines)
        mock_get.assert_called_once_with('https://parlament.mt/mt/test',
                                         referer=papi.PARLAMENT_URL)

    @patch('parlament.papi.cache.httpGet', side_effect=Exception('timeout'))
    def test_fetch_failure_returns_none(self, mock_get):
        self.assertIsNone(papi.get_agenda_lines_by_url('https://parlament.mt/mt/test'))


class TestGetPlenaryCandidates(unittest.TestCase):

    _LEG = {'TitleMT': 'Il-Hmistax-il Legislatura', 'Number': 15}

    def _sitting_with_audio(self, number, iso_date, url):
        sitting = _make_sitting(number, iso_date)
        sitting['Media'] = [{'IsVideo': False, 'Url': url}]
        return sitting

    @patch('parlament.papi.cache.httpHead')
    def test_builds_candidates(self, mock_head):
        sitting = self._sitting_with_audio(171, '2023-11-14T16:00:00', _RIGHT_URL)
        [candidate] = papi.get_plenary_candidates(self._LEG, [sitting])
        self.assertEqual(candidate['source_audio_path'], _RIGHT_URL)
        self.assertEqual(candidate['kind'], 'plenary')
        self.assertEqual(candidate['title'], 'Sessjoni Plenarja S15E171')
        self.assertEqual(candidate['link'], papi.PARLAMENT_URL + '/mt/test')
        self.assertEqual(candidate['source'], 'media-archive')
        self.assertEqual(candidate['pubdate'], papi.get_sitting_date(sitting))

    @patch('parlament.papi.cache.httpHead')
    def test_sitting_without_audio_skipped(self, mock_head):
        no_audio = _make_sitting(5, '2023-01-01T10:00:00')
        with_audio = self._sitting_with_audio(171, '2023-11-14T16:00:00', _RIGHT_URL)
        candidates = papi.get_plenary_candidates(self._LEG, [no_audio, with_audio])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['title'], 'Sessjoni Plenarja S15E171')

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_NO_AGENDA_HTML))
    @patch('parlament.papi.cache.httpHead')
    def test_description_built_lazily(self, mock_head, mock_get):
        sitting = self._sitting_with_audio(171, '2023-11-14T16:00:00', _RIGHT_URL)
        [candidate] = papi.get_plenary_candidates(self._LEG, [sitting])
        mock_get.assert_not_called()
        html, summary = candidate['build_texts']()
        self.assertIn('Seduta Nru: 171', summary)
        self.assertIn('Seduta Nru: 171', html)
        mock_get.assert_called_once()


class TestGetBareAudioUrl(unittest.TestCase):

    def test_no_audio_raises(self):
        sitting = _make_sitting(5, '2023-01-01T10:00:00')
        # Media list is already [] in _make_sitting
        with self.assertRaises(Exception, msg='Expected Exception when sitting has no audio media'):
            papi.get_bare_audio_url(sitting)

    def test_video_only_raises(self):
        sitting = _make_sitting(5, '2023-01-01T10:00:00')
        sitting['Media'] = [{'IsVideo': True, 'Url': '/Audio/video.mp4'}]
        with self.assertRaises(Exception):
            papi.get_bare_audio_url(sitting)

    @patch('parlament.papi.cache.httpHead')
    def test_returns_audio_url(self, mock_head):
        sitting = _make_sitting(171, '2023-11-14T16:00:00')
        url = '/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3'
        sitting['Media'] = [{'IsVideo': False, 'Url': url}]
        result = papi.get_bare_audio_url(sitting)
        self.assertEqual(result, url)


if __name__ == '__main__':
    unittest.main()
