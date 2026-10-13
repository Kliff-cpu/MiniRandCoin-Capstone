import unittest
from copy import deepcopy

from wallet import create_wallets
from reserves import ReserveLedger
from blockchain import (
    Blockchain,
    create_signed_transfer,
    verify_signed_transfer,
)


class SignedTransferTests(unittest.TestCase):
    def setUp(self):
        self.sender, self.recipient, self.reserve_agent = create_wallets()
        self.ledger = ReserveLedger(reserve_agent_address=self.reserve_agent.address)
        self.ledger.onramp(self.sender.address, 1000)
        self.chain = Blockchain(self.ledger, difficulty=2)

    def test_valid_transfer_mines_and_updates_balances(self):
        transaction = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.assertTrue(verify_signed_transfer(transaction))
        self.chain.add_transfer(transaction)
        self.assertEqual(self.ledger.balances[self.sender.address], 1000)
        mined, attempts = self.chain.mine_pending()
        self.assertGreaterEqual(attempts, 1)
        self.assertTrue(mined.hash.startswith("00"))
        self.assertEqual(self.ledger.balances[self.sender.address], 250)
        self.assertEqual(self.ledger.balances[self.recipient.address], 750)
        self.assertEqual(self.ledger.vault_fiat, 1000)
        self.assertEqual(self.ledger.circulating, 1000)
        self.assertTrue(self.ledger.invariant_ok())
        self.assertTrue(self.chain.verify_chain())
        self.assertTrue(self.chain.verify_inclusion(transaction["id"]))
        self.assertEqual(self.chain.lookup_transaction(transaction["id"])["block_hash"], mined.hash)
        self.assertEqual(self.ledger.events[-1]["type"], "TRANSFER_CONFIRMED")

    def test_reject_tampered_signature(self):
        transaction = create_signed_transfer(self.sender, self.recipient.address, 750)
        transaction["amount"] = 751
        self.assertFalse(verify_signed_transfer(transaction))
        with self.assertRaisesRegex(ValueError, "signature"):
            self.chain.add_transfer(transaction)
        self.assertEqual(len(self.chain.pending_transactions), 0)

    def test_reject_forged_sender(self):
        transaction = create_signed_transfer(self.sender, self.recipient.address, 750)
        transaction["sender"] = self.recipient.address
        with self.assertRaises(ValueError):
            self.chain.add_transfer(transaction)

    def test_reject_insufficient_funds(self):
        transaction = create_signed_transfer(self.sender, self.recipient.address, 1001)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            self.chain.add_transfer(transaction)
        self.assertTrue(self.ledger.invariant_ok())

    def test_reject_pending_overspend(self):
        first = create_signed_transfer(self.sender, self.recipient.address, 750)
        second = create_signed_transfer(self.sender, self.recipient.address, 300)
        self.chain.add_transfer(first)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            self.chain.add_transfer(second)
        self.assertEqual(len(self.chain.pending_transactions), 1)
        self.assertEqual(self.ledger.balances[self.sender.address], 1000)

    def test_reject_duplicate_and_replay(self):
        transfer = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.chain.add_transfer(transfer)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.chain.add_transfer(transfer)
        self.chain.mine_pending()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.chain.add_transfer(transfer)

    def test_reject_invalid_amounts(self):
        for amount in (0, -1, 1.5, True, "750"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    create_signed_transfer(self.sender, self.recipient.address, amount)

    def test_reject_transaction_malleability(self):
        transfer = create_signed_transfer(self.sender, self.recipient.address, 750)
        transfer["unexpected_field"] = "not signed"
        with self.assertRaises(ValueError):
            self.chain.add_transfer(transfer)

    def test_mined_block_tampering_is_detected(self):
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.chain.add_transfer(tx)
        self.chain.mine_pending()
        self.chain.chain[1].transactions[0]["amount"] = 1
        self.assertFalse(self.chain.verify_chain())
        self.assertFalse(self.chain.verify_inclusion(tx["id"]))

    def test_no_empty_mining(self):
        with self.assertRaises(ValueError):
            self.chain.mine_pending()
        self.assertEqual(len(self.chain.chain), 1)

    def test_reject_unbalanced_reserves(self):
        self.ledger.vault_fiat = 999
        transaction = create_signed_transfer(self.sender, self.recipient.address, 750)
        with self.assertRaisesRegex(ValueError, "invariant"):
            self.chain.add_transfer(transaction)


if __name__ == "__main__":
    unittest.main()
