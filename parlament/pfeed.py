# Parlament Podcast Feed

from parlament.podcastfeed import PodcastFeed
from feedgenerator import Enclosure

from lxml import etree
import os

UTF8 = 'utf8'

def init_feed():
    return PodcastFeed(
        title="Il-Podcast tal-Parlament",
        link="https://parlament.podcast.mt/",
        description="Dan il-Podcast huwa ġabra inuffiċjali tas-seduti tal-<a href=\"https://parlament.mt/\">Parlament ta' Malta</a>. Is-seduti jiġu ppublikati hawn il-ġurnata ta' wara li jseħħu. Għal aktar informazzjoni dwar dan il-podcast, żur <a href=\"https://parlament.podcast.mt/\">parlament.podcast.mt</a>.",
        language="mt",
        image_url = "https://parlament.podcast.mt/img/parlament-logo.jpg",
        owner="parlament@podcast.mt",
        author="Il-Parlament ta' Malta",
        category="News & Politics",
    )

def add_item(feed, title, description, link, audio_url, content_length='', duration=None, pubdate=None, unique_id=None, summary=None):
    feed.add_item(
        title=title,
        description=description,
        link=link,
        enclosures=[Enclosure(url=audio_url, length=content_length, mime_type="audio/mpeg")],
        unique_id=unique_id or audio_url,
        duration=duration,
        pubdate=pubdate,
        summary=summary,
    )

def _wrap_descriptions_in_cdata(tree):
    """Wrap each item's <description>, and the channel's own <description>,
    in a CDATA section instead of entity-escaping it. Both are
    XML-equivalent - any conformant parser decodes them to the same string
    - but CDATA is the conventional way podcast RSS feeds carry
    HTML-bearing fields and keeps the raw feed source human-readable. Left
    entity-escaped (skipped) in the vanishingly unlikely case the text
    contains a literal ']]>', which would prematurely close a CDATA
    section."""
    descriptions = tree.findall('.//item/description') + tree.findall('./channel/description')
    for description in descriptions:
        if description.text and ']]>' not in description.text:
            description.text = etree.CDATA(description.text)

def write_feed(feed, filename):
    tmp_filename = filename + '.tmp'
    try:
        with open(tmp_filename, 'w', encoding=UTF8) as fp:
            feed.write(fp, UTF8)
        tree = etree.parse(tmp_filename)
        _wrap_descriptions_in_cdata(tree)
        tree.write(filename, encoding=UTF8, pretty_print=True)
    finally:
        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)
