import io
import os
import tempfile
import unittest
from datetime import datetime, timezone

from parlament import pfeed

class TestParlamentFeed(unittest.TestCase):

    def test_init_feed(self):
        feed = pfeed.init_feed()
        self.assertEqual(feed.feed['title'], 'Il-Podcast tal-Parlament')

    def test_add_item_enclosure_present(self):
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(len(feed.items), 1)
        item = feed.items[0]
        self.assertEqual(len(item['enclosures']), 1,
            "Each feed item must have exactly one enclosure (media file)")
        enclosure = item['enclosures'][0]
        self.assertEqual(enclosure.url, audio_url)
        self.assertEqual(enclosure.length, '')
        self.assertEqual(enclosure.mime_type, 'audio/mpeg')

    def test_add_item_enclosure_with_content_length(self):
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            content_length='12345678',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        enclosure = feed.items[0]['enclosures'][0]
        self.assertEqual(enclosure.length, '12345678')

    def test_add_item_enclosure_length_fallback(self):
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            content_length='',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        enclosure = feed.items[0]['enclosures'][0]
        self.assertEqual(enclosure.length, '',
            "length should be empty string when content_length is not provided")

    def test_add_item_guid_present(self):
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        item = feed.items[0]
        self.assertIsNotNone(item['unique_id'],
            "Each feed item must have a unique_id (GUID) so podcast apps can track episodes")
        self.assertEqual(item['unique_id'], audio_url)

    def test_add_item_summary_present(self):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='<p>A test episode</p>',
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            summary='A test episode',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(feed.items[0]['summary'], 'A test episode')

    def test_add_item_summary_defaults_to_none(self):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        self.assertIsNone(feed.items[0]['summary'])

    def test_itunes_summary_emitted_when_present(self):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='<p>A test episode</p>',
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            summary='A test episode',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        out = io.StringIO()
        feed.write(out, 'utf8')
        self.assertIn('<itunes:summary>A test episode</itunes:summary>', out.getvalue())

    def test_itunes_summary_emitted_even_when_empty_string(self):
        # An empty summary is a data problem worth surfacing, not silently
        # dropping - distinguish it from summary genuinely absent (None).
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='<p>A test episode</p>',
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            summary='',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        out = io.StringIO()
        feed.write(out, 'utf8')
        self.assertIn('<itunes:summary/>', out.getvalue())

    def test_itunes_summary_omitted_when_absent(self):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        out = io.StringIO()
        feed.write(out, 'utf8')
        self.assertNotIn('itunes:summary', out.getvalue())

    def test_add_item_explicit_unique_id(self):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url='https://r2.parlament.podcast.mt/Audio/new-location.mp3',
            unique_id='https://r2.parlament.podcast.mt/Audio/original guid.mp3',
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(feed.items[0]['unique_id'],
            'https://r2.parlament.podcast.mt/Audio/original guid.mp3',
            "an explicitly stored guid must win over the enclosure URL")

class TestWriteFeedCdata(unittest.TestCase):

    def _write(self, description, summary=None):
        feed = pfeed.init_feed()
        pfeed.add_item(feed,
            title='Test Episode',
            description=description,
            link='https://parlament.mt/test',
            audio_url='https://parlament.mt/Audio/test.mp3',
            summary=summary,
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'podcast.rss')
            pfeed.write_feed(feed, path)
            return open(path, encoding='utf8').read()

    def test_html_description_wrapped_in_cdata_verbatim(self):
        # Content already carries its own entity-escaping (e.g. from
        # html.escape() upstream) for characters from the source text -
        # CDATA must not escape it a second time.
        content = self._write('<p>R&amp;D &lt;Committee&gt;</p><ul><li>Item</li></ul>')
        self.assertIn(
            '<description><![CDATA[<p>R&amp;D &lt;Committee&gt;</p><ul><li>Item</li></ul>]]></description>',
            content)

    def test_itunes_summary_not_wrapped_in_cdata(self):
        content = self._write('<p>desc</p>', summary='R&D <Committee>')
        self.assertIn('<itunes:summary>R&amp;D &lt;Committee&gt;</itunes:summary>', content)
        self.assertNotIn('<itunes:summary><![CDATA[', content)

    def test_literal_cdata_close_sequence_falls_back_to_escaping(self):
        # ']]>' inside the content would prematurely close a CDATA
        # section - skip CDATA for that (rare) case rather than emit
        # broken XML. The channel description is unaffected and still
        # gets CDATA-wrapped normally (it doesn't contain ']]>').
        content = self._write('<p>weird ]]> content</p>')
        self.assertIn(
            '<description>&lt;p&gt;weird ]]&gt; content&lt;/p&gt;</description>',
            content)

    def test_channel_description_cdata_wrapped_with_links(self):
        # The channel-level description carries real HTML links to both
        # parlament.mt and the podcast site, so it needs the same CDATA
        # treatment as per-item descriptions - not left entity-escaped.
        content = self._write('<p>desc</p>')
        self.assertIn(
            '<description><![CDATA[Dan il-Podcast huwa ġabra inuffiċjali', content)
        self.assertIn('<a href="https://parlament.mt/">', content)
        self.assertIn('<a href="https://parlament.podcast.mt/">', content)


if __name__ == '__main__':
    unittest.main()