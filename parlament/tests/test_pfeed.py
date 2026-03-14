import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from parlament import pfeed

def _make_head_response(content_length='12345678'):
    mock_response = MagicMock()
    mock_response.headers = {'Content-Length': content_length}
    return mock_response

class TestParlamentFeed(unittest.TestCase):

    def test_init_feed(self):
        feed = pfeed.init_feed()
        self.assertEqual(feed.feed['title'], 'Il-Podcast tal-Parlament')

    @patch('parlament.pfeed.cache.httpHead')
    def test_add_item_enclosure_present(self, mock_head):
        mock_head.return_value = _make_head_response('12345678')
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        mock_head.assert_called_once_with(audio_url)
        self.assertEqual(len(feed.items), 1)
        item = feed.items[0]
        self.assertEqual(len(item['enclosures']), 1,
            "Each feed item must have exactly one enclosure (media file)")
        enclosure = item['enclosures'][0]
        self.assertEqual(enclosure.url, audio_url)
        self.assertEqual(enclosure.length, '12345678')
        self.assertEqual(enclosure.mime_type, 'audio/mpeg')

    @patch('parlament.pfeed.cache.httpHead')
    def test_add_item_enclosure_length_fallback(self, mock_head):
        mock_response = MagicMock()
        mock_response.headers = {}
        mock_head.return_value = mock_response
        feed = pfeed.init_feed()
        audio_url = 'https://parlament.mt/Audio/test.mp3'
        pfeed.add_item(feed,
            title='Test Episode',
            description='A test episode',
            link='https://parlament.mt/test',
            audio_url=audio_url,
            pubdate=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        enclosure = feed.items[0]['enclosures'][0]
        self.assertEqual(enclosure.length, '',
            "length should fall back to empty string when Content-Length header is absent")

    @patch('parlament.pfeed.cache.httpHead')
    def test_add_item_guid_present(self, mock_head):
        mock_head.return_value = _make_head_response()
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