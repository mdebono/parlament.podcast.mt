# Parlament API

from datetime import datetime
import pytz, babel.dates

from parlament import cache

LEGISLATURE_ID = '506899'
PARLAMENT_URL = 'https://parlament.mt'
PARLAMENT_MEDIA_ARCHIVE_URL = PARLAMENT_URL + '/en/menues/reference-material/archives/media-archive/'
PARLAMENT_MEDIA_ARCHIVE_API_URL = PARLAMENT_URL + '/umbraco/Api/MediaArchiveApi/GetMediaForLegislature/?lang=mt&legislatureId=' + LEGISLATURE_ID
BABEL_MT_DATETIME_FORMAT = "EEEE, d 'ta''' MMMM yyyy HH:mm"

def get_leg():
    cache.httpFetch(PARLAMENT_MEDIA_ARCHIVE_URL)
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
    return [c for c in leg['Committees'] if c['CommitteeType'] == 'Plenary'][0]['Sittings']

def get_sitting_audio_url(sitting):
    audio_url = [m for m in sitting['Media'] if m['IsVideo'] == False]
    if len(audio_url) == 0:
        raise Exception('audio not found for sitting ' + get_sitting_number(sitting))
    else:
        return PARLAMENT_URL + audio_url[0]['Url']

def get_sitting_url(sitting):
    return PARLAMENT_URL + sitting['Url']

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

def get_episode_description(leg, sitting):
    text = '{leg_title} Seduta Nru: {episode:03} - {date}'
    date = get_sitting_date(sitting)
    return text.format(
        leg_title = get_leg_title(leg),
        episode = get_sitting_number(sitting),
        date = babel.dates.format_datetime(datetime=date, format=BABEL_MT_DATETIME_FORMAT, locale='mt'),
    )
