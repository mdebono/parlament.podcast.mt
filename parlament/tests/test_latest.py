import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytz

from parlament import latest, papi

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_LEG = {'Number': 15, 'Title': 'Fifteenth Legislature', 'TitleMT': 'Il-Ħmistax-il Leġiżlatura'}

def _make_meeting(**overrides):
    """Return a minimal GetLatestMediaFiles meeting dict (committee kind)."""
    meeting = {
        'MeetingTitles': [
            {'Language': 'en', 'Title': 'Public Accounts Committee'},
            {'Language': 'mt', 'Title': 'Kumitat dwar il-Kontijiet Pubbliċi'},
        ],
        'MeetingURL': '/15th-leg/pac/meeting-12/',
        'MeetingNo': '12',
        'MeetingDate': '2026-07-01T14:30:00',
        'IsPlenary': False,
        'IsSitting': True,
        'AudioURLs': ['/Audio/15thLeg/PAC/PAC%2012%2001-07-2026.mp3'],
        'VideoURLs': [],
    }
    meeting.update(overrides)
    return meeting

def _make_plenary(**overrides):
    return _make_meeting(
        MeetingTitles=[
            {'Language': 'en', 'Title': 'Plenary Session'},
            {'Language': 'mt', 'Title': 'Sessjoni Plenarja'},
        ],
        MeetingURL='/15th-leg/plenary-session/ps-171/',
        MeetingNo='171',
        IsPlenary=True,
        IsSitting=True,
        AudioURLs=['/Audio/15thLeg/Plenary/Plenary%20171%2014-11-2023%201600hrs.mp3'],
        **overrides,
    )

def _make_event(**overrides):
    return _make_meeting(
        MeetingTitles=[
            {'Language': 'en', 'Title': 'Conference on X'},
            {'Language': 'mt', 'Title': 'Konferenza dwar X'},
        ],
        MeetingURL='/15th-leg/events/conference-x/',
        MeetingNo='0',
        IsPlenary=False,
        IsSitting=False,
        AudioURLs=['/Audio/15thLeg/Events/Conference%20X.mp3'],
        **overrides,
    )


class TestUnwrapLatestMedia(unittest.TestCase):

    def test_wrapped_dict(self):
        meetings = [_make_meeting()]
        self.assertEqual(latest.unwrap_latest_media({'LatestMediaFiles': meetings}), meetings)

    def test_bare_list(self):
        meetings = [_make_meeting()]
        self.assertEqual(latest.unwrap_latest_media(meetings), meetings)

    def test_unknown_dict_returns_empty(self):
        self.assertEqual(latest.unwrap_latest_media({'SomethingElse': []}), [])

    def test_unknown_type_returns_empty(self):
        self.assertEqual(latest.unwrap_latest_media('nonsense'), [])


class TestGetLatestMedia(unittest.TestCase):

    @patch('parlament.latest.cache.httpPost')
    @patch('parlament.latest.cache.httpGet')
    def test_primes_cookies_then_posts(self, mock_get, mock_post):
        response = MagicMock()
        response.json.return_value = {'LatestMediaFiles': [_make_meeting()]}
        mock_post.return_value = response
        meetings = latest.get_latest_media()
        self.assertEqual(len(meetings), 1)
        mock_get.assert_called_once_with(latest.PARLAMENT_HOME_URL)
        mock_post.assert_called_once_with(
            latest.PARLAMENT_LATEST_MEDIA_API_URL, None,
            referer=latest.PARLAMENT_HOME_URL)
        response.raise_for_status.assert_called_once()


class TestGetMeetingTitle(unittest.TestCase):

    def test_prefers_maltese(self):
        self.assertEqual(latest.get_meeting_title(_make_meeting()),
                         'Kumitat dwar il-Kontijiet Pubbliċi')

    def test_falls_back_to_english(self):
        meeting = _make_meeting(MeetingTitles=[{'Language': 'en', 'Title': 'Only English'}])
        self.assertEqual(latest.get_meeting_title(meeting), 'Only English')

    def test_language_case_insensitive(self):
        meeting = _make_meeting(MeetingTitles=[{'Language': 'MT', 'Title': 'Bil-Malti'}])
        self.assertEqual(latest.get_meeting_title(meeting), 'Bil-Malti')

    def test_no_titles_raises(self):
        with self.assertRaises(ValueError):
            latest.get_meeting_title(_make_meeting(MeetingTitles=[]))


class TestGetMeetingKind(unittest.TestCase):

    def test_kinds(self):
        self.assertEqual(latest.get_meeting_kind(_make_plenary()), 'plenary')
        self.assertEqual(latest.get_meeting_kind(_make_meeting()), 'committee')
        self.assertEqual(latest.get_meeting_kind(_make_event()), 'event')


class TestParseMeetingDate(unittest.TestCase):

    _MALTA = pytz.timezone('Europe/Malta')

    def test_iso_naive_localized_to_malta(self):
        dt = latest.parse_meeting_date('2026-07-01T14:30:00')
        self.assertEqual(dt, self._MALTA.localize(datetime(2026, 7, 1, 14, 30)))

    def test_dotnet_epoch_ms(self):
        # 2023-11-14T15:00:00Z == 16:00 Malta (CET)
        ms = int(datetime(2023, 11, 14, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        dt = latest.parse_meeting_date('/Date({})/'.format(ms))
        self.assertEqual(dt.hour, 16)
        self.assertEqual(dt.utcoffset().total_seconds(), 3600)

    def test_dotnet_epoch_ms_with_offset_suffix(self):
        ms = int(datetime(2023, 11, 14, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        dt = latest.parse_meeting_date('/Date({}+0100)/'.format(ms))
        self.assertEqual(dt.hour, 16)

    def test_day_month_year_formats(self):
        dt = latest.parse_meeting_date('01/07/2026 14:30')
        self.assertEqual((dt.day, dt.month, dt.year, dt.hour, dt.minute), (1, 7, 2026, 14, 30))
        dt = latest.parse_meeting_date('01/07/2026')
        self.assertEqual((dt.day, dt.month, dt.year), (1, 7, 2026))

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            latest.parse_meeting_date('next Tuesday')
        with self.assertRaises(ValueError):
            latest.parse_meeting_date('')
        with self.assertRaises(ValueError):
            latest.parse_meeting_date(None)


class TestNormalizeAudioPath(unittest.TestCase):

    def test_relative_path_kept(self):
        self.assertEqual(latest.normalize_audio_path('/Audio/x%20y.mp3'), '/Audio/x%20y.mp3')

    def test_missing_leading_slash_added(self):
        self.assertEqual(latest.normalize_audio_path('Audio/x.mp3'), '/Audio/x.mp3')

    def test_absolute_parlament_url_stripped(self):
        self.assertEqual(
            latest.normalize_audio_path('https://parlament.mt/Audio/x%20y.mp3'),
            '/Audio/x%20y.mp3')

    def test_foreign_host_raises(self):
        with self.assertRaises(ValueError):
            latest.normalize_audio_path('https://evil.example/Audio/x.mp3')


class TestGetCandidates(unittest.TestCase):

    def test_video_only_skipped(self):
        meeting = _make_meeting(AudioURLs=[], VideoURLs=['/video.mp4'])
        self.assertEqual(latest.get_candidates(_LEG, [meeting]), [])

    def test_committee_candidate(self):
        [candidate] = latest.get_candidates(_LEG, [_make_meeting()])
        self.assertEqual(candidate['kind'], 'committee')
        self.assertEqual(candidate['title'], 'Kumitat dwar il-Kontijiet Pubbliċi M012')
        self.assertEqual(candidate['source'], 'latest-media')
        self.assertEqual(candidate['source_audio_path'],
                         '/Audio/15thLeg/PAC/PAC%2012%2001-07-2026.mp3')
        self.assertEqual(candidate['link'],
                         papi.PARLAMENT_URL + '/15th-leg/pac/meeting-12/')
        self.assertEqual(candidate['pubdate'].isoformat(), '2026-07-01T14:30:00+02:00')

    def test_committee_without_number_uses_date_title(self):
        [candidate] = latest.get_candidates(_LEG, [_make_meeting(MeetingNo='0')])
        self.assertEqual(candidate['title'],
                         "Kumitat dwar il-Kontijiet Pubbliċi - 1 ta' Lulju 2026")

    def test_plenary_candidate_matches_archive_title_format(self):
        [candidate] = latest.get_candidates(_LEG, [_make_plenary()])
        self.assertEqual(candidate['kind'], 'plenary')
        self.assertEqual(candidate['title'], 'Sessjoni Plenarja S15E171')

    def test_plenary_without_leg_skipped(self):
        self.assertEqual(latest.get_candidates(None, [_make_plenary()]), [])

    def test_event_candidate(self):
        [candidate] = latest.get_candidates(_LEG, [_make_event()])
        self.assertEqual(candidate['kind'], 'event')
        self.assertEqual(candidate['title'], "Konferenza dwar X - 1 ta' Lulju 2026")

    def test_multi_part_audio_becomes_one_candidate_per_file(self):
        meeting = _make_meeting(AudioURLs=['/Audio/part1.mp3', '/Audio/part2.mp3'])
        candidates = latest.get_candidates(_LEG, [meeting])
        self.assertEqual([c['title'] for c in candidates], [
            'Kumitat dwar il-Kontijiet Pubbliċi M012 (Parti 1 minn 2)',
            'Kumitat dwar il-Kontijiet Pubbliċi M012 (Parti 2 minn 2)',
        ])
        self.assertEqual([c['source_audio_path'] for c in candidates],
                         ['/Audio/part1.mp3', '/Audio/part2.mp3'])

    def test_bad_item_skipped_others_survive(self):
        bad = _make_meeting(MeetingDate='next Tuesday')
        candidates = latest.get_candidates(_LEG, [bad, _make_meeting()])
        self.assertEqual(len(candidates), 1)

    def test_foreign_audio_host_skipped(self):
        meeting = _make_meeting(AudioURLs=['https://evil.example/x.mp3'])
        self.assertEqual(latest.get_candidates(_LEG, [meeting]), [])


class TestBuildDescription(unittest.TestCase):

    @patch('parlament.papi.get_agenda_by_url', return_value='PUNT\n- Xi ħaġa')
    def test_committee_description_with_agenda(self, mock_agenda):
        [candidate] = latest.get_candidates(_LEG, [_make_meeting()])
        description = candidate['build_description']()
        self.assertTrue(description.startswith(
            'Kumitat dwar il-Kontijiet Pubbliċi Laqgħa Nru: 012 - '))
        self.assertIn('\n\nAġenda:\nPUNT\n- Xi ħaġa', description)
        mock_agenda.assert_called_once_with(
            papi.PARLAMENT_URL + '/mt/15th-leg/pac/meeting-12/')

    @patch('parlament.papi.get_agenda_by_url', return_value=None)
    def test_committee_description_without_agenda(self, mock_agenda):
        [candidate] = latest.get_candidates(_LEG, [_make_meeting()])
        description = candidate['build_description']()
        self.assertNotIn('Aġenda', description)

    @patch('parlament.papi.get_agenda_by_url')
    def test_event_description_never_fetches_agenda(self, mock_agenda):
        [candidate] = latest.get_candidates(_LEG, [_make_event()])
        description = candidate['build_description']()
        self.assertTrue(description.startswith('Konferenza dwar X - '))
        mock_agenda.assert_not_called()

    @patch('parlament.papi.get_agenda_by_url', return_value=None)
    def test_plenary_description_matches_archive_format(self, mock_agenda):
        [candidate] = latest.get_candidates(_LEG, [_make_plenary()])
        description = candidate['build_description']()
        self.assertTrue(description.startswith(
            'Il-Ħmistax-il Leġiżlatura Seduta Nru: 171 - '))


if __name__ == '__main__':
    unittest.main()
