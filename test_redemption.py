import unittest
from copy import deepcopy

from blockchain import Blockchain, create_signed_transfer
from redemption import RedemptionService, create_signed_redemption, verify_signed_redemption
from reserves import ReserveLedger
from wallet import create_wallets


class OffRampTests(unittest.TestCase):
    def setUp(self):
        self.sender, self.recipient, self.reserve_agent = create_wallets()
        self.ledger = ReserveLedger(reserve_agent_address=self.reserve_agent.address)
        self.onramp_event = self.ledger.onramp(self.sender.address, 1000)
        self.chain = Blockchain(self.ledger, difficulty=2)
        self.transfer = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.service = RedemptionService(self.chain, min_confirmations=1)

    def mined(self):
        self.chain.add_transfer(self.transfer)
        self.block, _ = self.chain.mine_pending()

    def request(self, amount=750):
        return create_signed_redemption(self.recipient, self.transfer['id'], amount)

    def snapshot(self):
        return (
            self.ledger.vault_fiat,
            self.ledger.circulating,
            deepcopy(self.ledger.balances),
            deepcopy(self.ledger.receipts),
            deepcopy(self.ledger.events),
        )

    def test_signed_redemption_rebalances_ledger(self):
        self.mined()
        request = self.request()
        self.assertTrue(verify_signed_redemption(request))
        receipt = self.service.redeem(request)
        self.assertEqual(receipt['paid_local'], 750)
        self.assertEqual(receipt['burned_mzar'], 750)
        self.assertEqual(receipt['payout_status'], 'SIMULATED')
        self.assertEqual(receipt['reference_transaction_id'], self.transfer['id'])
        self.assertEqual(receipt['confirmed_block_hash'], self.block.hash)
        self.assertEqual(receipt['confirmation_depth_at_payout'], 1)
        self.assertEqual(self.ledger.balances[self.sender.address], 250)
        self.assertEqual(self.ledger.balances[self.recipient.address], 0)
        self.assertEqual(self.ledger.vault_fiat, 250)
        self.assertEqual(self.ledger.circulating, 250)
        self.assertEqual(len(self.ledger.receipts), 1)
        self.assertEqual(self.ledger.events[-1]['type'], 'OFF_RAMP')
        self.assertTrue(self.ledger.invariant_ok())
        self.assertTrue(self.chain.verify_inclusion(self.transfer['id']))

    def test_premature_offramp_rejected_before_mining(self):
        request = self.request()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            self.service.redeem(request)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_wallet_cannot_redeem(self):
        self.mined()
        forged = create_signed_redemption(self.sender, self.transfer['id'], 750)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'not the transfer recipient'):
            self.service.redeem(forged)
        self.assertEqual(self.snapshot(), before)

    def test_modified_amount_breaks_signature(self):
        self.mined()
        request = self.request()
        request['amount'] = 751
        self.assertFalse(verify_signed_redemption(request))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.service.redeem(request)
        self.assertEqual(self.snapshot(), before)

    def test_reject_wrong_transfer_id(self):
        self.mined()
        request = create_signed_redemption(self.recipient, '0'*32, 750)
        with self.assertRaisesRegex(ValueError, 'not confirmed'):
            self.service.redeem(request)

    def test_reject_invalid_amount_types(self):
        for amount in (-1, 0, 1.2, True, '750'):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.request(amount)

    def test_reject_amount_greater_than_transfer(self):
        self.mined()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unredeemed'):
            self.service.redeem(self.request(751))
        self.assertEqual(self.snapshot(), before)

    def test_reject_replay_of_same_request(self):
        self.mined()
        request = self.request()
        self.service.redeem(request)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'already been processed'):
            self.service.redeem(request)
        self.assertEqual(self.snapshot(), before)

    def test_reject_second_redemption_of_same_transfer(self):
        self.mined()
        self.service.redeem(self.request())
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unredeemed'):
            self.service.redeem(self.request(1))
        self.assertEqual(self.snapshot(), before)

    def test_confirmation_policy_blocks_early_payout(self):
        self.mined()
        policy = RedemptionService(self.chain, min_confirmations=2)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'confirmations'):
            policy.redeem(self.request())
        self.assertEqual(self.snapshot(), before)

    def test_chain_tamper_blocks_redemption(self):
        self.mined()
        self.block.transactions[0]['amount'] = 1
        with self.assertRaisesRegex(ValueError, 'blockchain verification failed'):
            self.service.redeem(self.request())

    def test_reject_unbalanced_ledger(self):
        self.mined()
        self.ledger.vault_fiat = 999
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'invariant'):
            self.service.redeem(self.request())
        self.assertEqual(self.snapshot(), before)

    def test_partial_redemptions(self):
        self.mined()
        first = self.service.redeem(self.request(300))
        second = self.service.redeem(self.request(450))
        self.assertNotEqual(first['receipt_id'], second['receipt_id'])
        self.assertEqual(self.ledger.vault_fiat, 250)
        self.assertEqual(self.ledger.circulating, 250)
        self.assertEqual(self.ledger.balances[self.recipient.address], 0)
        self.assertEqual(len(self.ledger.receipts), 2)
        self.assertTrue(self.ledger.invariant_ok())

    def test_signature_key_mismatch_rejected(self):
        self.mined()
        request = self.request()
        request['public_key'] = self.sender.public_key_hex
        self.assertFalse(verify_signed_redemption(request))
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.service.redeem(request)

    def test_non_dict_request_rejected(self):
        self.mined()
        for obj in (None, [], [1], 'hello'):
            with self.subTest(value=obj):
                with self.assertRaises(ValueError):
                    self.service.redeem(obj)


if __name__ == '__main__':
    unittest.main()
