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
        self.assertEqual(enclosure.mime_type, 'audio/mpeg')

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

if __name__ == '__main__':
    unittest.main()