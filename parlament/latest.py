# Homepage "Latest Media Files" source
#
# The parlament.mt homepage ("Follow Parliament" > "Latest Media Files")
# lists recent media for plenary sittings, committee meetings and other
# events (conferences etc.). It is backed by the LiveParliamentApi, which
# unlike the media archive is not limited to plenary sittings.

import re
from datetime import datetime, timezone
import pytz, babel.dates
from urllib.parse import urlsplit

from parlament import cache, papi

PARLAMENT_HOME_URL = papi.PARLAMENT_URL + '/'
PARLAMENT_LATEST_MEDIA_API_URL = papi.PARLAMENT_URL + '/umbraco/Api/LiveParliamentApi/GetLatestMediaFiles/'
BABEL_MT_DATE_FORMAT = "d 'ta''' MMMM yyyy"

_DOTNET_DATE_RE = re.compile(r'^/Date\((-?\d+)(?:[+-]\d{4})?\)/$')

def get_latest_media():
    cache.httpGet(PARLAMENT_HOME_URL)
    response = cache.httpPost(PARLAMENT_LATEST_MEDIA_API_URL, None, referer=PARLAMENT_HOME_URL)
    response.raise_for_status()
    return unwrap_latest_media(response.json())

def unwrap_latest_media(data):
    """Return the list of meetings from a GetLatestMediaFiles response.

    The response shape was derived from the site's JavaScript rather than a
    captured payload, so unwrap defensively: accept either the expected
    {'LatestMediaFiles': [...]} wrapper or a bare list, and degrade to an
    empty list (with a warning) on anything else."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        meetings = data.get('LatestMediaFiles')
        if isinstance(meetings, list):
            return meetings
        print('Warning: unexpected GetLatestMediaFiles response keys: {}'.format(sorted(data.keys())))
    else:
        print('Warning: unexpected GetLatestMediaFiles response type: {}'.format(type(data).__name__))
    return []

def get_meeting_title(meeting, lang='mt'):
    titles = meeting.get('MeetingTitles') or []
    for wanted in (lang, 'en'):
        for title in titles:
            if (title.get('Language') or '').lower() == wanted and title.get('Title'):
                return title['Title']
    if titles and titles[0].get('Title'):
        return titles[0]['Title']
    raise ValueError('meeting has no title')

def get_meeting_kind(meeting):
    if meeting.get('IsPlenary'):
        return 'plenary'
    elif meeting.get('IsSitting'):
        return 'committee'
    else:
        return 'event'

def get_meeting_number(meeting):
    try:
        return int(meeting.get('MeetingNo') or 0)
    except (TypeError, ValueError):
        return 0

def parse_meeting_date(value):
    """Parse a MeetingDate into an aware datetime in Europe/Malta.

    The exact wire format is unknown (ISO, .NET /Date(ms)/ and dd/MM/yyyy
    are all plausible for an Umbraco API), so try each in turn."""
    local = pytz.timezone('Europe/Malta')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('missing meeting date')
    value = value.strip()

    m = _DOTNET_DATE_RE.match(value)
    if m:
        utc_dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        return utc_dt.astimezone(local)

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        dt = None
    if dt is None:
        for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y'):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise ValueError('unrecognised meeting date format: {!r}'.format(value))
    if dt.tzinfo is None:
        return local.localize(dt)
    return dt.astimezone(local)

def normalize_audio_path(url):
    """Return a bare site-relative audio path (e.g. /Audio/...) so both
    sources produce the same catalogue key. AudioURLs may be relative or
    absolute; foreign hosts are rejected."""
    parts = urlsplit(url)
    if parts.netloc and parts.netloc not in ('parlament.mt', 'www.parlament.mt'):
        raise ValueError('audio URL on foreign host: {}'.format(url))
    path = parts.path
    if not path.startswith('/'):
        path = '/' + path
    return path

def _format_day_mt(date):
    return babel.dates.format_date(date=date.date(), format=BABEL_MT_DATE_FORMAT, locale='mt')

def _meeting_title(leg, meeting):
    title = get_meeting_title(meeting)
    kind = get_meeting_kind(meeting)
    number = get_meeting_number(meeting)
    if kind == 'plenary':
        return '{title} S{season:02}E{episode:03}'.format(
            title=title, season=papi.get_leg_number(leg), episode=number)
    elif kind == 'committee' and number:
        return '{title} M{number:03}'.format(title=title, number=number)
    else:
        return '{title} - {date}'.format(
            title=title, date=_format_day_mt(parse_meeting_date(meeting['MeetingDate'])))

def _build_texts(leg, meeting):
    title = get_meeting_title(meeting)
    kind = get_meeting_kind(meeting)
    number = get_meeting_number(meeting)
    date = parse_meeting_date(meeting['MeetingDate'])
    link = papi.path_to_mt_url(meeting['MeetingURL'])
    lines = None
    if kind != 'event' and meeting.get('MeetingURL'):
        lines = papi.get_agenda_lines_by_url(link)
    # Always delegate to the one shared builder (also used by app.py's
    # backfill), so a committee's wording can never drift from what a
    # re-match against the archive would produce - label=None covers
    # events and committees without a meeting number, where there's no
    # meaningful "Nru:" to show.
    if kind == 'plenary':
        return papi.build_sitting_texts('Seduta', papi.get_leg_title(leg), number, date, lines, link)
    elif kind == 'committee' and number:
        return papi.build_sitting_texts('Laqgħa', title, number, date, lines, link)
    else:
        return papi.build_sitting_texts(None, title, None, date, lines, link)

def _meeting_candidates(leg, meeting):
    audio_urls = meeting.get('AudioURLs') or []
    if not audio_urls:
        return []  # video-only or not yet published; re-evaluated next run
    if get_meeting_kind(meeting) == 'plenary' and leg is None:
        # Without legislature data the S..E.. title can't be built; the
        # sitting is normally picked up from the media archive anyway.
        print('Warning: skipping plenary item {!r}: no legislature data'.format(
            meeting.get('MeetingURL')))
        return []
    pubdate = parse_meeting_date(meeting['MeetingDate'])
    title = _meeting_title(leg, meeting)
    candidates = []
    for part, audio_url in enumerate(audio_urls, start=1):
        part_title = title
        if len(audio_urls) > 1:
            # RSS allows one enclosure per item, so a meeting with several
            # audio files becomes one episode per file.
            part_title += ' (Parti {} minn {})'.format(part, len(audio_urls))
        candidates.append({
            'source_audio_path': normalize_audio_path(audio_url),
            'kind': get_meeting_kind(meeting),
            'title': part_title,
            'link': papi.path_to_mt_url(meeting['MeetingURL']),
            'pubdate': pubdate,
            'source': 'latest-media',
            'build_texts':
                lambda leg=leg, meeting=meeting: _build_texts(leg, meeting),
        })
    return candidates

def get_candidates(leg, meetings):
    """Build candidate dicts (see app.py) from GetLatestMediaFiles meetings.
    Items that cannot be interpreted are skipped with a warning so one bad
    entry never takes down the whole source."""
    candidates = []
    for meeting in meetings:
        try:
            candidates.extend(_meeting_candidates(leg, meeting))
        except Exception as e:
            print('Warning: skipping latest-media item {!r}: {}'.format(
                meeting.get('MeetingURL'), e))
    return candidates
