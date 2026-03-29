import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from parlament import papi

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


# Use only the path, not the domain, to match how correct_audio_url constructs new_url
_BASE = '/Audio/14thLeg/Plenary/'
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
        url = '/Audio/14thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3'
        sitting['Media'] = [{'IsVideo': False, 'Url': url}]
        result = papi.get_bare_audio_url(sitting)
        self.assertEqual(result, url)


if __name__ == '__main__':
    unittest.main()
