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

if __name__ == '__main__':
    unittest.main()