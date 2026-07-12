# Parlament API

from datetime import datetime
from html import escape as html_escape
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

def _split_on_br(el):
    """Split an element's content into one line per <br>-separated segment,
    every <br> starting a new line unconditionally. Used for committee
    agenda items, which are commonly packed into a single <p> as
    "1. Foo;<br />2. Bar; u<br />3. Baz" rather than separate <p> elements
    - text_content() would otherwise silently run them together with no
    separator at all, since <br> contributes no text of its own. Unlike
    _split_row_into_lines, there's no sentence-final-punctuation heuristic
    here: these enumerated items typically end in ';', not '.', so that
    heuristic would merge them right back together."""
    lines = []
    buf = []

    def flush():
        text = ' '.join(''.join(buf).split())
        buf.clear()
        if text:
            lines.append(text)

    if el.text:
        buf.append(el.text)
    for child in el:
        if child.tag == 'br':
            flush()
        else:
            buf.append(child.text_content())
        if child.tail:
            buf.append(child.tail)
    flush()
    return lines

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

def _extract_agenda_lines(html):
    """Extract the agenda from a sitting/meeting page as structured
    ('heading'|'item', text) lines, or None. The page renders the agenda
    inside <div id="orders">, but its inner markup differs by page type:

    - plenary sitting pages: bold <p> elements are section headings (e.g.
      ORDNIJIET TAL-ĠURNATA) and each table row is one or more agenda items.
      Non-bold <p> elements are incidental text (notes, captions) and are
      not treated as agenda items on these pages.
    - committee meeting pages: agenda items are plain (non-bold) <p>
      elements with no table at all.

    A page is classified as table-based (plenary-style) the moment any
    <table> appears anywhere in #orders, so a stray non-bold <p> on such a
    page is never mistaken for a committee-style agenda item.

    Table-nested <p> elements are excluded here because their text is
    already extracted via the <tr> branch below."""
    doc = lxml.html.fromstring(html)
    orders = doc.xpath('//div[@id="orders"]')
    if not orders:
        return None
    has_table = bool(orders[0].xpath('.//table'))
    lines = []
    for el in orders[0].iter():
        if el.tag == 'p' and not any(a.tag == 'table' for a in el.iterancestors()):
            if 'bold' in (el.get('style') or ''):
                text = ' '.join(el.text_content().split())
                if text:
                    lines.append(('heading', text))
            elif not has_table:
                for line in _split_on_br(el):
                    lines.append(('item', line))
        elif el.tag == 'tr':
            for line in _split_row_into_lines(el):
                lines.append(('item', line))
    if not lines:
        return None
    return lines

def lines_to_plain(lines):
    """Render structured agenda lines as plain text: headings raw, items
    prefixed '- ', one per line."""
    return '\n'.join(text if kind == 'heading' else '- ' + text for kind, text in lines)

_NUMBERED_ITEM_RE = re.compile(r'^\d+\.\s*')

def lines_to_html(lines):
    """Render structured agenda lines as HTML: each heading becomes a bold
    paragraph, and each run of consecutive items becomes one list block.
    If every item in a run is itself numbered ("1. Foo;"), it's rendered
    as <ol> with the redundant leading number stripped (the <ol> already
    supplies it); otherwise <ul>, text unchanged. Text is HTML-escaped
    since it's sourced from the parliament site and may itself contain
    '<' or '&'.

    Every block-level piece (each <p>, the whole list, each <li>) is
    joined with a real '\\n' rather than concatenated directly. Whitespace
    between block elements is insignificant to any real HTML renderer, so
    this is invisible there - but some podcast apps show a collapsed
    preview by naively stripping tags without inserting a separator at the
    boundary, which runs adjacent blocks together with no space at all
    ("...16:00Aġenda:ORDNIJIET..."); the '\\n' survives that stripping."""
    parts = []
    items = []

    def flush_items():
        if not items:
            return
        if all(_NUMBERED_ITEM_RE.match(text) for text in items):
            tag, rendered = 'ol', [_NUMBERED_ITEM_RE.sub('', text, count=1) for text in items]
        else:
            tag, rendered = 'ul', items
        parts.append('<{tag}>'.format(tag=tag)
                     + '\n'.join('<li>{}</li>'.format(html_escape(text, quote=False)) for text in rendered)
                     + '</{tag}>'.format(tag=tag))
        items.clear()

    for kind, text in lines:
        if kind == 'heading':
            flush_items()
            parts.append('<p><strong>{}</strong></p>'.format(html_escape(text, quote=False)))
        else:
            items.append(text)
    flush_items()
    return '\n'.join(parts)

def parse_agenda_html(html):
    """Extract the agenda from a sitting/meeting page as plain text, or
    None if the page or the agenda section is unavailable. A convenience
    composition of _extract_agenda_lines + lines_to_plain kept as a public,
    network-free utility (and the main test surface for the DOM-parsing
    rules); the live fetch path goes through get_agenda_lines_by_url
    instead, since it needs the structured form to also render HTML."""
    lines = _extract_agenda_lines(html)
    return lines_to_plain(lines) if lines else None

def get_agenda_lines_by_url(url):
    """Fetch a sitting/meeting page and return its agenda as structured
    lines, or None if the page or the agenda section is unavailable."""
    try:
        response = cache.httpGet(url, referer=PARLAMENT_URL)
        response.raise_for_status()
        return _extract_agenda_lines(response.content)
    except Exception as e:
        print('Warning: could not fetch agenda from {}: {}'.format(url, e))
        return None

def get_sitting_agenda_lines(sitting):
    """Fetch the sitting page and return its agenda as structured lines, or
    None if the page or the agenda section is unavailable."""
    return get_agenda_lines_by_url(get_sitting_url_mt(sitting))

def build_sitting_texts(label, title, number, date, lines):
    """Build (description_html, summary) for an episode. label is 'Seduta'
    (plenary), 'Laqgħa' (committee), or None for a meeting with no
    meaningful number to show (events, committees without one) - in which
    case the preamble is just "title - date" and number is ignored.
    lines is the already-fetched structured agenda (from
    get_agenda_lines_by_url, or None) - callers control the one fetch this
    needs, and both text forms are built from the same source of truth so
    they can never drift apart."""
    date_str = babel.dates.format_datetime(datetime=date, format=BABEL_MT_DATETIME_FORMAT, locale='mt')
    if label:
        preamble = '{title} {label} Nru: {number:03} - {date}'.format(
            title=title, label=label, number=number, date=date_str)
    else:
        preamble = '{title} - {date}'.format(title=title, date=date_str)
    summary = preamble
    html = '<p>{}</p>'.format(html_escape(preamble, quote=False))
    if lines:
        summary += '\n\nAġenda:\n' + lines_to_plain(lines)
        # '\n' between blocks (see lines_to_html) so a naive tag-stripping
        # preview doesn't run "...16:00" straight into "Aġenda:...".
        html += '\n<p><strong>Aġenda:</strong></p>\n' + lines_to_html(lines)
    return html, summary

def label_and_title_for_sitting(kind, leg, sitting):
    """Return (label, title) for building a sitting's description text -
    the single source of truth for how each kind is labelled and whose
    title it uses, shared by the live plenary path and the archive-backed
    backfill path (both operate on the same sitting dict shape). Plenary's
    canonical subject is the legislature's own title; committees use their
    own sitting title. Returns (None, None) for a kind the archive has no
    equivalent for (e.g. 'event')."""
    if kind == 'plenary':
        return 'Seduta', get_leg_title(leg)
    elif kind == 'committee':
        return 'Laqgħa', get_sitting_title(sitting)
    else:
        return None, None

def get_episode_texts(leg, sitting):
    """Return (description_html, summary) for a plenary sitting."""
    label, title = label_and_title_for_sitting('plenary', leg, sitting)
    return build_sitting_texts(
        label,
        title,
        get_sitting_number(sitting),
        get_sitting_date(sitting),
        get_sitting_agenda_lines(sitting),
    )

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
            'build_texts':
                lambda leg=leg, sitting=sitting: get_episode_texts(leg, sitting),
        })
    return candidates
