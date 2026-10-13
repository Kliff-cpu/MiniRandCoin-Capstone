import copy
import json
import threading
import unittest

from api import create_server
from blockchain import create_signed_transfer
from demo import call
from redemption import create_signed_redemption
from verification import verify_exported_chain, lookup_verified_transaction
from wallet import Wallet


class EndToEndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.sender = Wallet('Sender')
        self.recipient = Wallet('Recipient')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def call(self, method, path, payload=None):
        return call(self.base, method, path, payload)

    def make_deposit(self):
        status, data = self.call('POST', '/onramp', {'address': self.sender.address, 'amount': 1000})
        self.assertEqual(status, 201)
        return data

    def mine_transfer(self):
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        status, _ = self.call('POST', '/transactions/new', tx)
        self.assertEqual(status, 202)
        status, mined = self.call('POST', '/mine')
        self.assertEqual(status, 201)
        return tx, mined

    def test_end_to_end_onramp_transfer_mine_offramp(self):
        deposit = self.make_deposit()
        self.assertEqual(deposit['event']['minted_mzar'], 1000)
        status, before = self.call('GET', '/state')
        self.assertEqual(before['balances_mzar'][self.sender.address], 1000)
        self.assertEqual(before['vault_reserves_zar'], 1000)

        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        status, queued = self.call('POST', '/transactions/new', tx)
        self.assertEqual(status, 202)
        self.assertEqual(queued['transaction_id'], tx['id'])
        status, pending_state = self.call('GET', '/state')
        self.assertEqual(pending_state['balances_mzar'][self.sender.address], 1000)
        self.assertEqual(pending_state['pending_transactions'], 1)
        status, not_yet = self.call('GET', '/verify/' + tx['id'])
        self.assertEqual(status, 404)

        status, mined = self.call('POST', '/mine')
        self.assertEqual(status, 201)
        self.assertTrue(mined['chain_valid'])
        self.assertTrue(mined['block']['hash'].startswith('00'))
        status, proof = self.call('GET', '/verify/' + tx['id'])
        self.assertEqual(status, 200)
        self.assertTrue(proof['included'])
        self.assertTrue(proof['signature_valid'])
        self.assertEqual(proof['block_hash'], mined['block']['hash'])
        status, mid = self.call('GET', '/state')
        self.assertEqual(mid['balances_mzar'][self.sender.address], 250)
        self.assertEqual(mid['balances_mzar'][self.recipient.address], 750)

        redemption = create_signed_redemption(self.recipient, tx['id'], 750)
        status, redeemed = self.call('POST', '/offramp', redemption)
        self.assertEqual(status, 201)
        self.assertEqual(redeemed['receipt']['paid_local'], 750)
        self.assertEqual(redeemed['receipt']['payout_status'], 'SIMULATED')
        status, after = self.call('GET', '/state')
        self.assertEqual(after['balances_mzar'][self.sender.address], 250)
        self.assertEqual(after['balances_mzar'][self.recipient.address], 0)
        self.assertEqual(after['vault_reserves_zar'], 250)
        self.assertEqual(after['circulating_mzar'], 250)
        self.assertTrue(after['reserve_invariant_ok'])

        status, events = self.call('GET', '/events')
        self.assertEqual(status, 200)
        self.assertEqual([x['type'] for x in events['events']],
                         ['ON_RAMP', 'TRANSFER_CONFIRMED', 'OFF_RAMP'])

    def test_invalid_signature_and_overspend_do_not_mutate_state(self):
        self.make_deposit()
        tampered = create_signed_transfer(self.sender, self.recipient.address, 750)
        tampered['amount'] = 751
        status, _ = self.call('POST', '/transactions/new', tampered)
        self.assertEqual(status, 400)
        overspend = create_signed_transfer(self.sender, self.recipient.address, 1001)
        status, _ = self.call('POST', '/transactions/new', overspend)
        self.assertEqual(status, 400)
        status, state = self.call('GET', '/state')
        self.assertEqual(state['pending_transactions'], 0)
        self.assertEqual(state['balances_mzar'][self.sender.address], 1000)
        self.assertEqual(state['vault_reserves_zar'], 1000)

    def test_no_early_redemption_and_no_double_redemption(self):
        self.make_deposit()
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.assertEqual(self.call('POST', '/transactions/new', tx)[0], 202)
        redeem = create_signed_redemption(self.recipient, tx['id'], 750)
        self.assertEqual(self.call('POST', '/offramp', redeem)[0], 400)
        self.assertEqual(self.call('POST', '/mine')[0], 201)
        self.assertEqual(self.call('POST', '/offramp', redeem)[0], 201)
        self.assertEqual(self.call('POST', '/offramp', redeem)[0], 400)
        status, state = self.call('GET', '/state')
        self.assertEqual(state['vault_reserves_zar'], 250)

    def test_independent_verification_and_tamper_detection(self):
        self.make_deposit()
        tx, mined = self.mine_transfer()
        status, payload = self.call('GET', '/chain')
        self.assertEqual(status, 200)
        self.assertTrue(verify_exported_chain(payload['chain'], payload['difficulty'])['valid'])
        result = lookup_verified_transaction(payload['chain'], tx['id'], payload['difficulty'])
        self.assertEqual(result['block_hash'], mined['block']['hash'])
        corrupt = copy.deepcopy(payload['chain'])
        corrupt[1]['transactions'][0]['amount'] = 749
        self.assertFalse(verify_exported_chain(corrupt, payload['difficulty'])['valid'])

    def test_explorer_links_to_real_verified_transaction(self):
        self.make_deposit()
        tx, mined = self.mine_transfer()
        from urllib.request import urlopen
        with urlopen(self.base + '/explorer') as response:
            text = response.read().decode('utf-8')
        self.assertIn(tx['id'], text)
        with urlopen(self.base + '/explorer/tx/' + tx['id']) as response:
            detail = response.read().decode('utf-8')
        self.assertIn(tx['id'], detail)
        self.assertIn(mined['block']['hash'], detail)
        self.assertNotIn('PRIVATE KEY', detail)


if __name__ == '__main__':
    unittest.main()
