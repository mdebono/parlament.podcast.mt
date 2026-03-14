# Parlament Podcast Feed

from parlament.podcastfeed import PodcastFeed
from parlament import cache
from curl_cffi import requests
from feedgenerator import Enclosure

from lxml import etree

UTF8 = 'utf8'

def init_feed():
    return PodcastFeed(
        title="Il-Podcast tal-Parlament",
        link="https://parlament.podcast.mt/",
        description="Dan il-Podcast huwa ġabra inuffiċjali tas-seduti tal-Parlament ta' Malta. Is-seduti jiġu ppublikati hawn il-ġurnata ta' wara li jseħħu. Għal aktar informazzjoni, żur is-sit ta' dan il-podcast.",
        language="mt",
        image_url = "https://parlament.podcast.mt/img/parlament-logo.jpg",
        owner="parlament@mdebono.com",
        author="Il-Parlament ta' Malta",
        category="News & Politics",
    )

def add_item(feed, title, description, link, audio_url, duration=None, pubdate=None):
    try:
        response = cache.httpHead(audio_url)
        content_length = response.headers.get('content-length', '')
    except requests.exceptions.RequestException as e:
        print('Warning: could not fetch Content-Length for {}: {}'.format(audio_url, e))
        content_length = ''
    feed.add_item(
        title=title,
        description=description,
        link=link,
        enclosures=[Enclosure(url=audio_url, length=content_length, mime_type="audio/mpeg")],
        unique_id=audio_url,
        duration=duration,
        pubdate=pubdate,
    )

def write_feed(feed, filename):
    tmp_filename = filename + '.tmp'
    with open(tmp_filename, 'w', encoding=UTF8) as fp:
        feed.write(fp, UTF8)
    tree = etree.parse(tmp_filename)
    tree.write(filename, encoding=UTF8, pretty_print=True)
