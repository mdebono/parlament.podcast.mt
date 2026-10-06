import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit, parse_qs

from parlament import cache


def _response(status_code, content=b'ok', json=None):
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.url = 'https://parlament.mt/test'
    r.headers = {}
    r.json.return_value = json
    return r


class _Base(unittest.TestCase):

    def setUp(self):
        cache.cache.clear()
        patches = [
            patch.object(cache, '_refused', None),
            patch.object(cache, '_last_request', None),
            patch.object(cache, 'GAP_SECONDS', 0),
            patch.object(cache, 'VIA', ''),
            patch.object(cache, 'VIA_KEY', ''),
            patch('parlament.cache.write_cache'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(cache.cache.clear)


class TestHttpGetRetry(_Base):

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_success(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(200)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.request.call_count, 1)
        mock_sleep.assert_not_called()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_retries_on_transient_503_then_succeeds(self, mock_session, mock_sleep):
        mock_session.request.side_effect = [_response(503), _response(200)]
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.request.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_gives_up_after_persistent_503(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(503)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 503)
        self.assertEqual(mock_session.request.call_count, 1 + len(cache.RETRY_BACKOFF_SECONDS))

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_404(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(404)
        result = cache.httpGet('https://parlament.mt/test')
        self.assertEqual(result.status_code, 404)
        self.assertEqual(mock_session.request.call_count, 1)
        mock_sleep.assert_not_called()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_403_is_not_retried_and_stops_later_requests(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(403)
        first = cache.httpGet('https://parlament.mt/a')
        second = cache.httpGet('https://parlament.mt/b')
        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 403)
        self.assertEqual(mock_session.request.call_count, 1)
        mock_sleep.assert_not_called()
        # the request not sent is not cached, so a kept cache.pkl asks again
        self.assertNotIn(('GET', 'https://parlament.mt/b'), cache.cache)

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_gap_between_requests(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(200)
        with patch.object(cache, 'GAP_SECONDS', 2):
            cache.httpGet('https://parlament.mt/a')
            cache.httpGet('https://parlament.mt/b')
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertGreater(mock_sleep.call_args[0][0], 1)


class TestHttpPostRetry(_Base):

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_success(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(200)
        result = cache.httpPost('https://parlament.mt/test', None)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.request.call_count, 1)
        self.assertEqual(mock_session.request.call_args[0][0], 'POST')
        mock_sleep.assert_not_called()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_retries_on_transient_503_then_succeeds(self, mock_session, mock_sleep):
        mock_session.request.side_effect = [_response(503), _response(200)]
        result = cache.httpPost('https://parlament.mt/test', None)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(mock_session.request.call_count, 2)
        mock_sleep.assert_called_once()

    @patch('parlament.cache.time.sleep')
    @patch('parlament.cache._session')
    def test_no_retry_on_404(self, mock_session, mock_sleep):
        mock_session.request.return_value = _response(404)
        result = cache.httpPost('https://parlament.mt/test', None)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(mock_session.request.call_count, 1)
        mock_sleep.assert_not_called()

    def test_rejects_a_body(self):
        with self.assertRaises(ValueError):
            cache.httpPost('https://parlament.mt/test', 'a=1')


class TestViaWorker(_Base):

    def setUp(self):
        super().setUp()
        p = patch.object(cache, 'VIA', 'http://127.0.0.1:8787')
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def _query(mock_session):
        url = mock_session.get.call_args[0][0]
        self_parts = urlsplit(url)
        return self_parts, {k: v[0] for k, v in parse_qs(self_parts.query).items()}

    @patch('parlament.cache._session')
    def test_get_goes_through_the_worker(self, mock_session):
        mock_session.get.return_value = _response(200, b'<html/>')
        result = cache.httpGet('https://parlament.mt/mt/page/', referer='https://parlament.mt')
        parts, q = self._query(mock_session)
        self.assertEqual(parts.netloc, '127.0.0.1:8787')
        self.assertEqual(q, {'u': 'https://parlament.mt/mt/page/', 'ref': 'https://parlament.mt'})
        mock_session.request.assert_not_called()
        self.assertEqual(result.content, b'<html/>')
        self.assertEqual(result.url, 'https://parlament.mt/mt/page/')

    @patch('parlament.cache._session')
    def test_post_goes_through_the_worker(self, mock_session):
        mock_session.get.return_value = _response(200, b'{}')
        cache.httpPost('https://parlament.mt/umbraco/Api/X/Y/?lang=mt', None, referer='https://parlament.mt/')
        _, q = self._query(mock_session)
        self.assertEqual(q['m'], 'POST')
        self.assertEqual(q['u'], 'https://parlament.mt/umbraco/Api/X/Y/?lang=mt')
        mock_session.post.assert_not_called()

    @patch('parlament.cache._session')
    def test_head_reads_the_workers_json(self, mock_session):
        mock_session.get.return_value = _response(200, json={
            'url': 'https://parlament.mt/a.mp3', 'status': 200, 'bytes': 1234, 'type': 'audio/mpeg'})
        result = cache.httpHead('https://parlament.mt/a.mp3')
        _, q = self._query(mock_session)
        self.assertEqual(q['m'], 'HEAD')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['content-length'], '1234')

    @patch('parlament.cache._session')
    def test_head_refused_by_parlament(self, mock_session):
        mock_session.get.return_value = _response(200, json={'url': 'https://parlament.mt/a.mp3', 'status': 403})
        result = cache.httpHead('https://parlament.mt/a.mp3')
        self.assertEqual(result.status_code, 403)
        self.assertIsNotNone(cache._refused)

    @patch('parlament.cache._session')
    def test_key_header(self, mock_session):
        mock_session.get.return_value = _response(200)
        with patch.object(cache, 'VIA_KEY', 'secret'):
            cache.httpGet('https://parlament.mt/')
        self.assertEqual(mock_session.get.call_args[1]['headers']['x-fetch-key'], 'secret')


if __name__ == '__main__':
    unittest.main()
