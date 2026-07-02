import unittest
from unittest.mock import patch, MagicMock

from parlament import cache


def _response(status_code, content=b'ok'):
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.url = 'https://parlament.mt/test'
    r.headers = {}
    return r


class TestHttpGetRetry(unittest.TestCase):

    def setUp(self):
        cache.cache.clear()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_success(self, mock_session, mock_sleep):
        mock_session.get.return_value = _response(200)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.get.call_count, 1)
        mock_sleep.assert_not_called()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_retries_on_transient_403_then_succeeds(self, mock_session, mock_sleep):
        mock_session.get.side_effect = [_response(403), _response(200)]
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_gives_up_after_persistent_403(self, mock_session, mock_sleep):
        mock_session.get.return_value = _response(403)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 403)
        self.assertEqual(mock_session.get.call_count, 1 + len(cache.RETRY_BACKOFF_SECONDS))

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_404(self, mock_session, mock_sleep):
        mock_session.get.return_value = _response(404)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 404)
        self.assertEqual(mock_session.get.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
