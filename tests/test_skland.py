import threading
import time
import unittest
from unittest.mock import Mock, patch

import app
from maabase import skland


class SklandLoginTests(unittest.TestCase):
    def test_scan_exchange_uses_matching_native_api_and_keeps_signing_token(self):
        responses = [
            {'status': 0, 'msg': 'OK', 'data': {'token': 'account-token'}},
            {'status': 0, 'msg': 'OK', 'data': {'code': 'grant-code'}},
            {'code': 0, 'message': 'OK', 'timestamp': 1234,
             'data': {'cred': 'credential', 'token': 'signing-token'}},
        ]
        with patch.object(skland, '_request', side_effect=responses) as request:
            result = skland.credential_from_scan_code('scan-code')
        self.assertEqual(result, skland.Credential('credential', 'signing-token', 1234))
        args, kwargs = request.call_args_list[-1]
        self.assertEqual(args[0], skland.SKLAND_BASE + '/api/v1/user/auth/generate_cred_by_code')
        self.assertNotIn('dId', kwargs['headers'])
        self.assertEqual(kwargs['body'], {'kind': 1, 'code': 'grant-code'})
        self.assertNotIn('credential', repr(result).lower().replace('credential(', ''))
        self.assertNotIn('signing-token', repr(result))

    def test_generated_signing_token_avoids_an_extra_refresh(self):
        client = skland.Client(skland.Credential('cred', 'token'))
        with patch.object(skland, '_request', return_value={'code': 0, 'message': 'OK'}) as request:
            client.get('/api/v1/game/player/binding')
        self.assertEqual(request.call_count, 1)
        self.assertTrue(request.call_args.args[0].endswith('/binding'))
        self.assertEqual(request.call_args.kwargs['headers']['token'], 'token')

    def test_request_timestamp_advances_with_clock_offset(self):
        with patch.object(skland.time, 'time', return_value=1000):
            client = skland.Client(skland.Credential('cred', 'token', 1100))
        with patch.object(skland.time, 'time', side_effect=[1010, 1030]), patch.object(
                skland, '_request', return_value={'code': 0, 'message': 'OK'}) as request:
            client.get('/first')
            client.get('/second')
        self.assertEqual([call.kwargs['headers']['timestamp'] for call in request.call_args_list], ['1108', '1128'])

    def test_waiting_and_upstream_rejection_are_distinct(self):
        with patch.object(skland, '_request', return_value={'status': 100, 'msg': '未扫码'}):
            self.assertIsNone(skland.get_scan_code('scan'))
        with patch.object(skland, '_request', return_value={'status': 999, 'msg': '二维码已过期'}):
            with self.assertRaisesRegex(skland.SklandError, '二维码已过期'):
                skland.get_scan_code('scan')

    def test_credential_error_preserves_diagnostic_without_response_secrets(self):
        error = skland._upstream_error('生成凭据失败', {
            'code': 10001, 'message': '设备信息无效', 'data': {'token': 'never-print-me'}})
        self.assertIn('10001', str(error))
        self.assertIn('设备信息无效', str(error))
        self.assertNotIn('never-print-me', str(error))

    def test_string_credentials_still_refresh_once(self):
        client = skland.Client('legacy-cred')
        with patch.object(skland, '_request', side_effect=[
            {'code': 0, 'message': 'OK', 'data': {'token': 'new-token'}},
            {'code': 0, 'message': 'OK'}, {'code': 0, 'message': 'OK'},
        ]) as request:
            client.get('/first')
            client.get('/second')
        self.assertEqual(request.call_count, 3)
        self.assertTrue(request.call_args_list[0].args[0].endswith('/auth/refresh'))


class ScanSessionTests(unittest.TestCase):
    def setUp(self):
        self.scan_id = 'test-scan'
        app.SCAN_SESSIONS[self.scan_id] = {'expires_at': time.time() + 120, 'poll_lock': threading.Lock()}

    def tearDown(self):
        app.SCAN_SESSIONS.pop(self.scan_id, None)

    def test_concurrent_polls_redeem_scan_exactly_once(self):
        entered, release = threading.Event(), threading.Event()
        def exchange(_):
            entered.set()
            self.assertTrue(release.wait(3))
            return skland.Credential('cred', 'token')
        client = Mock()
        client.bindings.return_value = [{'uid': 'game-uid'}]
        results = []
        with patch.object(app, 'get_scan_code', return_value='single-use'), patch.object(
                app, 'credential_from_scan_code', side_effect=exchange) as redeem, patch.object(
                app, 'SklandClient', return_value=client):
            thread = threading.Thread(target=lambda: results.append(app._scan_status(self.scan_id)))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(app._scan_status(self.scan_id), {'status': 'processing'})
            finally:
                release.set()
                thread.join(3)
            self.assertEqual(app._scan_status(self.scan_id)['status'], 'authorized')
            self.assertEqual(redeem.call_count, 1)
            self.assertEqual(client.bindings.call_count, 1)
        self.assertEqual(results[0]['status'], 'authorized')

    def test_bindings_retry_reuses_authorized_client_and_extends_selection_window(self):
        client = Mock()
        client.bindings.side_effect = [skland.SklandError('暂时不可用'), [{'uid': 'game-uid'}]]
        with patch.object(app, 'get_scan_code', return_value='single-use'), patch.object(
                app, 'credential_from_scan_code', return_value=skland.Credential('cred', 'token')) as redeem, patch.object(
                app, 'SklandClient', return_value=client):
            with self.assertRaises(skland.SklandError):
                app._scan_status(self.scan_id)
            self.assertEqual(app._scan_status(self.scan_id)['status'], 'authorized')
            self.assertEqual(redeem.call_count, 1)
        self.assertGreater(app.SCAN_SESSIONS[self.scan_id]['expires_at'], time.time() + 590)
        self.assertIs(app.SCAN_SESSIONS[self.scan_id]['client'], client)

    def test_expired_unscanned_session_is_rejected(self):
        app.SCAN_SESSIONS[self.scan_id]['expires_at'] = time.time() - 1
        with self.assertRaisesRegex(ValueError, '二维码已过期'):
            app._scan_status(self.scan_id)


if __name__ == '__main__':
    unittest.main()
