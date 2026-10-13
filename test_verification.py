import copy
import unittest

from blockchain import Blockchain, create_signed_transfer, Block
from redemption import RedemptionService, create_signed_redemption
from reserves import ReserveLedger
from verification import block_hash, verify_exported_chain, lookup_verified_transaction
from wallet import create_wallets


class IndependentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.sender, self.recipient, self.agent = create_wallets()
        self.ledger = ReserveLedger(self.agent.address)
        self.ledger.onramp(self.sender.address, 1000)
        self.chain = Blockchain(self.ledger, difficulty=2)
        self.payment = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.chain.add_transfer(self.payment)
        self.block, _ = self.chain.mine_pending()
        self.snapshot = [b.to_dict() for b in self.chain.chain]

    def test_valid_export_without_live_ledger(self):
        report = verify_exported_chain(self.snapshot, difficulty=2)
        self.assertTrue(report["valid"])
        self.assertEqual(report["blocks_checked"], 2)
        self.assertEqual(report["transactions_checked"], 1)

    def test_transaction_lookup(self):
        row = lookup_verified_transaction(self.snapshot, self.payment["id"])
        self.assertTrue(row["included"])
        self.assertTrue(row["signature_valid"])
        self.assertEqual(row["amount_mzar"], 750)
        self.assertEqual(row["block_hash"], self.block.hash)
        self.assertEqual(row["confirmations"], 1)

    def test_unknown_transaction(self):
        self.assertIsNone(lookup_verified_transaction(self.snapshot, "f" * 32))

    def test_direct_tamper_detected(self):
        bad = copy.deepcopy(self.snapshot)
        bad[1]["transactions"][0]["amount"] = 751
        self.assertFalse(verify_exported_chain(bad)["valid"])
        with self.assertRaises(ValueError):
            lookup_verified_transaction(bad, self.payment["id"])

    def test_forged_remined_data_still_fails_signature(self):
        bad = copy.deepcopy(self.snapshot)
        bad[1]["transactions"][0]["amount"] = 751
        bad[1]["nonce"] = 0
        bad[1]["hash"] = block_hash(bad[1])
        while not bad[1]["hash"].startswith("00"):
            bad[1]["nonce"] += 1
            bad[1]["hash"] = block_hash(bad[1])
        report = verify_exported_chain(bad)
        self.assertFalse(report["valid"])
        self.assertIn("signed", report["error"])

    def test_break_previous_hash_link(self):
        bad = copy.deepcopy(self.snapshot)
        bad[1]["previous_hash"] = "f" * 64
        bad[1]["nonce"] = 0
        bad[1]["hash"] = block_hash(bad[1])
        while not bad[1]["hash"].startswith("00"):
            bad[1]["nonce"] += 1
            bad[1]["hash"] = block_hash(bad[1])
        report = verify_exported_chain(bad)
        self.assertFalse(report["valid"])
        self.assertIn("link", report["error"])

    def test_missing_or_extra_block_field(self):
        for changed in ("remove", "add"):
            bad = copy.deepcopy(self.snapshot)
            if changed == "remove":
                del bad[1]["nonce"]
            else:
                bad[1]["fake"] = 0
            self.assertFalse(verify_exported_chain(bad)["valid"])

    def test_reject_boolean_nonce_and_difficulty(self):
        bad = copy.deepcopy(self.snapshot)
        bad[1]["nonce"] = True
        self.assertFalse(verify_exported_chain(bad)["valid"])
        self.assertFalse(verify_exported_chain(self.snapshot, True)["valid"])

    def test_genesis_tamper(self):
        bad = copy.deepcopy(self.snapshot)
        bad[0]["timestamp"] = 3
        bad[0]["hash"] = block_hash(bad[0])
        self.assertFalse(verify_exported_chain(bad)["valid"])

    def test_after_redemption_chain_remains_valid(self):
        service = RedemptionService(self.chain, min_confirmations=1)
        service.redeem(create_signed_redemption(self.recipient, self.payment["id"], 750))
        self.assertTrue(verify_exported_chain(self.snapshot)["valid"])
        self.assertTrue(self.chain.verify_inclusion(self.payment["id"]))
        self.assertEqual(self.ledger.vault_fiat, 250)
        self.assertTrue(self.ledger.invariant_ok())

    def test_invalid_chain_type(self):
        for invalid in (None, "hello", [], {}, [1]):
            with self.subTest(invalid=invalid):
                self.assertFalse(verify_exported_chain(invalid)["valid"])

    def test_duplicate_signed_transaction_in_export(self):
        bad = copy.deepcopy(self.snapshot)
        duplicate = copy.deepcopy(bad[1])
        duplicate["index"] = 2
        duplicate["previous_hash"] = bad[1]["hash"]
        duplicate["nonce"] = 0
        duplicate["hash"] = block_hash(duplicate)
        while not duplicate["hash"].startswith("00"):
            duplicate["nonce"] += 1
            duplicate["hash"] = block_hash(duplicate)
        bad.append(duplicate)
        report = verify_exported_chain(bad)
        self.assertFalse(report["valid"])
        self.assertIn("duplicate", report["error"])


if __name__ == "__main__":
    unittest.main()
