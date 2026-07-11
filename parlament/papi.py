# Parlament API

from datetime import datetime
import re
import pytz, babel.dates
import lxml.html

from parlament import cache

_PLENARY_AUDIO_RE = re.compile(
    r'^(.*/)Plenary((?:%20)+)(\d+)%20(\d{2}-\d{2}-\d{4})%20(\d{4})hrs\.mp3$',
    re.IGNORECASE,
)

LEGISLATURE_ID = '541382'
PARLAMENT_URL = 'https://parlament.mt'
PARLAMENT_MEDIA_ARCHIVE_URL = PARLAMENT_URL + '/en/menues/reference-material/archives/media-archive/'
PARLAMENT_MEDIA_ARCHIVE_API_URL = PARLAMENT_URL + '/umbraco/Api/MediaArchiveApi/GetMediaForLegislature/?lang=mt&legislatureId=' + LEGISLATURE_ID
BABEL_MT_DATETIME_FORMAT = "EEEE, d 'ta''' MMMM yyyy HH:mm"

def get_leg():
    cache.httpGet(PARLAMENT_MEDIA_ARCHIVE_URL)
    response = cache.httpPost(PARLAMENT_MEDIA_ARCHIVE_API_URL, None, referer=PARLAMENT_MEDIA_ARCHIVE_URL)
    response.raise_for_status()
    return response.json()

def get_leg_title(leg, lang='mt'):
    if lang == 'mt':
        return leg['TitleMT']
    elif lang == 'en':
        return leg['Title']
    else:
        raise Exception('unknown language ' + lang)

def get_leg_number(leg):
    return leg['Number']

def get_plenary_sittings(leg):
    plenary = [c for c in leg['Committees'] if c['CommitteeType'] == 'Plenary']
    if not plenary:
        raise ValueError('No plenary committee found in legislature data')
    return plenary[0]['Sittings']

def get_bare_audio_url(sitting):
    audio_url = [m for m in sitting['Media'] if not m['IsVideo']]
    if len(audio_url) == 0:
        raise Exception('audio not found for sitting ' + str(get_sitting_number(sitting)))
    else:
        audio_url = audio_url[0]['Url']
        return correct_audio_url(sitting, audio_url)

def get_sitting_audio_url(sitting):
    return PARLAMENT_URL + get_bare_audio_url(sitting)

def get_audio_content_length(audio_url):
    """Return the Content-Length header value for the given audio_url, or '' if unavailable."""
    try:
        response = cache.httpHead(audio_url)
        return response.headers.get('content-length', '')
    except Exception as e:
        print(f'Warning: could not fetch Content-Length for {audio_url}: {e}')
        return ''

def get_sitting_url(sitting):
    return PARLAMENT_URL + sitting['Url']

def path_to_mt_url(path):
    """Return the Maltese-language URL for a site path.

    The API returns language-neutral paths (e.g. /15th-leg/plenary-session/...)
    which the site renders in English by default; the Maltese version lives
    under the /mt/ prefix."""
    if path.startswith('/en/'):
        path = path[3:]
    if not path.startswith('/mt/'):
        path = '/mt' + path
    return PARLAMENT_URL + path

def get_sitting_url_mt(sitting):
    """Return the Maltese-language URL of the sitting page."""
    return path_to_mt_url(sitting['Url'])

def get_sitting_title(sitting):
    return sitting['Title']

def get_sitting_number(sitting):
    return sitting['Number']

def get_sitting_date(sitting):
    local = pytz.timezone('Europe/Malta')
    naive = datetime.fromisoformat(sitting['Date'])
    local_dt = local.localize(naive)
    return local_dt

def get_episode_title(leg, sitting):
    text = '{title} S{season:02}E{episode:03}'
    return text.format(
        title = get_sitting_title(sitting),
        season = get_leg_number(leg),
        episode = get_sitting_number(sitting),
    )

def correct_audio_url(sitting, audio_url):
    """If the episode number embedded in *audio_url* doesn't match the sitting
    number, try to build a corrected URL and verify it with an HTTP HEAD
    request.  Returns the corrected URL when the HEAD succeeds (2xx), or the
    original URL unchanged when it either already matches, uses an unrecognised
    format, or the corrected URL cannot be verified."""
    sitting_number = get_sitting_number(sitting)
    m = _PLENARY_AUDIO_RE.match(audio_url)
    if m is None:
        return audio_url
    base, sep, url_episode_str = m.group(1), m.group(2), m.group(3)
    if int(url_episode_str) == sitting_number:
        return audio_url

    date = get_sitting_date(sitting)
    new_url = (
        '{base}Plenary{sep}{ep:03d}%20{d:02d}-{mo:02d}-{y:04d}%20{h:02d}{mi:02d}hrs.mp3'
        .format(
            base=base,
            sep=sep,
            ep=sitting_number,
            d=date.day, mo=date.month, y=date.year,
            h=date.hour, mi=date.minute,
        )
    )
    print(
        'Warning: sitting {:03d} contains wrong episode {:s}\n'
        'with URL: {}\n'
        'trying corrected URL: {}'.format(sitting_number, url_episode_str, audio_url, new_url)
    )
    try:
        response = cache.httpHead(PARLAMENT_URL + new_url)
        if 200 <= response.status_code < 300:
            print('Corrected URL verified (HTTP {}): {}'.format(response.status_code, new_url))
            return new_url
        else:
            print(
                'Warning: corrected URL returned HTTP {} - keeping original'.format(
                    response.status_code
                )
            )
    except Exception as e:
        print('Warning: could not verify corrected URL: {} - keeping original'.format(e))
    return audio_url

_SENTENCE_END_RE = re.compile(r'[.!?:]\s*$')

def _split_row_into_lines(el):
    """Split a <tr>'s content into text lines, breaking at <p> and <br>
    boundaries. Most rows are a single line, but some (e.g. the opening
    sitting's ceremonial programme) pack many agenda steps into one cell
    using <p>/<br> instead of separate rows. A <br>/<p> boundary only starts
    a new line if the text so far ends in sentence-final punctuation;
    otherwise it's treated as a mid-sentence wrap and merged with what
    follows, since the source HTML uses <br> for both purposes."""
    lines = []
    buf = []

    def flush():
        text = ' '.join(''.join(buf).split())
        buf.clear()
        if not text:
            return
        if lines and not _SENTENCE_END_RE.search(lines[-1]):
            lines[-1] = lines[-1] + ' ' + text
        else:
            lines.append(text)

    def walk(node):
        if node.text:
            buf.append(node.text)
        for child in node:
            if child.tag in ('br', 'p'):
                flush()
                if child.tag == 'p':
                    walk(child)
                    flush()
            else:
                walk(child)
            if child.tail:
                buf.append(child.tail)

    walk(el)
    flush()
    return lines

def parse_agenda_html(html):
    """Extract the agenda from a sitting page as plain-text lines, or None.

    The sitting page renders the agenda inside <div id="orders">: bold <p>
    elements are section headings (e.g. ORDNIJIET TAL-ĠURNATA) and each table
    row is one or more agenda items."""
    doc = lxml.html.fromstring(html)
    orders = doc.xpath('//div[@id="orders"]')
    if not orders:
        return None
    lines = []
    for el in orders[0].iter():
        if (el.tag == 'p' and 'bold' in (el.get('style') or '')
                and not any(a.tag == 'table' for a in el.iterancestors())):
            text = ' '.join(el.text_content().split())
            if text:
                lines.append(text)
        elif el.tag == 'tr':
            for line in _split_row_into_lines(el):
                lines.append('- ' + line)
    if not lines:
        return None
    return '\n'.join(lines)

def get_agenda_by_url(url):
    """Fetch a sitting/meeting page and return its agenda as plain text, or
    None if the page or the agenda section is unavailable."""
    try:
        response = cache.httpGet(url, referer=PARLAMENT_URL)
        response.raise_for_status()
        return parse_agenda_html(response.content)
    except Exception as e:
        print('Warning: could not fetch agenda from {}: {}'.format(url, e))
        return None

def get_sitting_agenda(sitting):
    """Fetch the sitting page and return its agenda as plain text, or None if
    the page or the agenda section is unavailable."""
    return get_agenda_by_url(get_sitting_url_mt(sitting))

def get_episode_description(leg, sitting):
    text = '{leg_title} Seduta Nru: {episode:03} - {date}'
    date = get_sitting_date(sitting)
    description = text.format(
        leg_title = get_leg_title(leg),
        episode = get_sitting_number(sitting),
        date = babel.dates.format_datetime(datetime=date, format=BABEL_MT_DATETIME_FORMAT, locale='mt'),
    )
    agenda = get_sitting_agenda(sitting)
    if agenda:
        description += '\n\nAġenda:\n' + agenda
    return description

def get_plenary_candidates(leg, sittings):
    """Build candidate dicts (see app.py) for plenary sittings from the media
    archive. Sittings without usable audio are skipped with a warning.
    Descriptions are built lazily so the agenda page is only fetched for
    sittings that are new to the catalogue."""
    candidates = []
    for sitting in sittings:
        try:
            audio_path = get_bare_audio_url(sitting)
        except Exception as e:
            print('Warning: skipping sitting {}: {}'.format(get_sitting_number(sitting), e))
            continue
        candidates.append({
            'source_audio_path': audio_path,
            'kind': 'plenary',
            'title': get_episode_title(leg, sitting),
            'link': get_sitting_url(sitting),
            'pubdate': get_sitting_date(sitting),
            'source': 'media-archive',
            'build_description':
                lambda leg=leg, sitting=sitting: get_episode_description(leg, sitting),
        })
    return candidates
