import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

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


class TestParseAgendaHtml(unittest.TestCase):

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


class TestGetEpisodeDescription(unittest.TestCase):

    _LEG = {'TitleMT': 'Il-Hmistax-il Legislatura', 'Number': 15}

    def _sitting(self):
        return _make_sitting(1, '2025-06-30T16:00:00')

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_AGENDA_HTML))
    def test_description_includes_agenda(self, mock_get):
        description = papi.get_episode_description(self._LEG, self._sitting())
        self.assertIn('Il-Hmistax-il Legislatura Seduta Nru: 001', description)
        self.assertIn('\n\nAġenda:\nMOZZJONIJIET\n', description)
        self.assertIn('- Mozzjoni Nru 15 - Xi Haga', description)
        mock_get.assert_called_once_with(papi.PARLAMENT_URL + '/mt/test', referer=papi.PARLAMENT_URL)

    @patch('parlament.papi.cache.httpGet', return_value=_page_response(_NO_AGENDA_HTML))
    def test_description_without_agenda_unchanged(self, mock_get):
        description = papi.get_episode_description(self._LEG, self._sitting())
        self.assertNotIn('Aġenda', description)
        self.assertTrue(description.startswith('Il-Hmistax-il Legislatura Seduta Nru: 001'))

    @patch('parlament.papi.cache.httpGet', side_effect=Exception('timeout'))
    def test_description_survives_fetch_failure(self, mock_get):
        description = papi.get_episode_description(self._LEG, self._sitting())
        self.assertNotIn('Aġenda', description)
        self.assertIn('Seduta Nru: 001', description)


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
