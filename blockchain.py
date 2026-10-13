import hashlib
import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone

from reserves import ReserveLedger
from wallet import Wallet, address_from_public_key


TRANSACTION_FIELDS = {
    "id", "type", "sender", "recipient", "amount", "timestamp_utc",
    "public_key", "signature",
}


def _sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_address(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 40:
        return False
    try:
        bytes.fromhex(value)
        return True
    except ValueError:
        return False


def create_signed_transfer(sender: Wallet, recipient_address: str, amount: int) -> dict:
    if not _valid_address(recipient_address):
        raise ValueError("invalid recipient address")
    if type(amount) is not int or amount <= 0:
        raise ValueError("amount must be a positive whole number of mZAR")

    body = {
        "id": uuid.uuid4().hex,
        "type": "TRANSFER",
        "sender": sender.address,
        "recipient": recipient_address,
        "amount": amount,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "public_key": sender.public_key_hex,
    }
    return {**body, "signature": sender.sign_payload(body)}


def verify_signed_transfer(transaction: dict) -> bool:
    if not isinstance(transaction, dict) or set(transaction) != TRANSACTION_FIELDS:
        return False

    if transaction["type"] != "TRANSFER":
        return False
    if type(transaction["amount"]) is not int or transaction["amount"] <= 0:
        return False
    if not _valid_address(transaction["sender"]):
        return False
    if not _valid_address(transaction["recipient"]):
        return False
    if transaction["sender"] == transaction["recipient"]:
        return False
    if not isinstance(transaction["id"], str) or len(transaction["id"]) != 32:
        return False
    try:
        bytes.fromhex(transaction["id"])
    except ValueError:
        return False
    if not isinstance(transaction["timestamp_utc"], str):
        return False
    if not isinstance(transaction["public_key"], str):
        return False
    if not isinstance(transaction["signature"], str):
        return False

    try:
        actual_address = address_from_public_key(transaction["public_key"])
    except ValueError:
        return False
    if transaction["sender"] != actual_address:
        return False

    payload = {key: value for key, value in transaction.items() if key != "signature"}
    return Wallet.verify_payload(
        payload, transaction["signature"], transaction["public_key"]
    )


@dataclass
class Block:
    index: int
    timestamp: int
    transactions: list[dict]
    previous_hash: str
    nonce: int = 0
    hash: str = ""

    def __post_init__(self):
        self.transactions = deepcopy(self.transactions)
        self.hash = self.compute_hash()

    def payload(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }

    def compute_hash(self) -> str:
        return _sha256(self.payload())

    def mine(self, difficulty: int) -> int:
        attempts = 1
        while not self.hash.startswith("0" * difficulty):
            self.nonce += 1
            self.hash = self.compute_hash()
            attempts += 1
        return attempts

    def to_dict(self) -> dict:
        return {**deepcopy(self.payload()), "hash": self.hash}


class Blockchain:
    def __init__(self, reserve_ledger: ReserveLedger, difficulty: int = 2):
        if type(difficulty) is not int or not 1 <= difficulty <= 5:
            raise ValueError("difficulty must be an integer from 1 to 5")
        self.ledger = reserve_ledger
        self.difficulty = difficulty
        self.chain = [Block(0, 0, [], "0" * 64)]
        self.pending_transactions = []

    def _existing_ids(self) -> set[str]:
        return {
            tx["id"]
            for block in self.chain
            for tx in block.transactions
        } | {tx["id"] for tx in self.pending_transactions}

    @staticmethod
    def _apply_projected(transaction: dict, balances: dict[str, int]) -> None:
        sender = transaction["sender"]
        recipient = transaction["recipient"]
        amount = transaction["amount"]
        if balances.get(sender, 0) < amount:
            raise ValueError("insufficient mZAR balance")
        balances[sender] = balances.get(sender, 0) - amount
        balances[recipient] = balances.get(recipient, 0) + amount

    def _validate_pending(self, proposed: dict | None = None):
        if not self.ledger.invariant_ok():
            raise ValueError("reserve ledger invariant is broken")
        balances = dict(self.ledger.balances)
        existing_chain_ids = {
            tx["id"] for block in self.chain for tx in block.transactions
        }
        seen = set(existing_chain_ids)
        sequence = self.pending_transactions + ([proposed] if proposed is not None else [])
        for tx in sequence:
            if not verify_signed_transfer(tx):
                raise ValueError("invalid transaction signature or structure")
            if tx["id"] in seen:
                raise ValueError("duplicate transaction ID")
            seen.add(tx["id"])
            self._apply_projected(tx, balances)

    def add_transfer(self, transaction: dict) -> str:
        self._validate_pending(transaction)
        self.pending_transactions.append(deepcopy(transaction))
        return transaction["id"]

    def mine_pending(self) -> tuple[Block, int]:
        if not self.pending_transactions:
            raise ValueError("no pending transactions to mine")
        if not self.verify_chain():
            raise RuntimeError("cannot mine onto an invalid chain")
        self._validate_pending()

        block = Block(
            index=len(self.chain),
            timestamp=int(time.time()),
            transactions=self.pending_transactions,
            previous_hash=self.chain[-1].hash,
        )
        attempts = block.mine(self.difficulty)
        self.ledger.record_confirmed_transfers(
            block.transactions, block.index, block.hash
        )
        self.chain.append(block)
        self.pending_transactions.clear()
        return block, attempts

    def verify_chain(self) -> bool:
        genesis = self.chain[0]
        expected_genesis = Block(0, 0, [], "0" * 64)
        if genesis.to_dict() != expected_genesis.to_dict():
            return False

        seen = set()
        for i, block in enumerate(self.chain):
            if block.hash != block.compute_hash():
                return False
            if i == 0:
                continue
            previous = self.chain[i - 1]
            if block.index != i or block.previous_hash != previous.hash:
                return False
            if not block.hash.startswith("0" * self.difficulty):
                return False
            if not block.transactions:
                return False
            for tx in block.transactions:
                if not verify_signed_transfer(tx) or tx["id"] in seen:
                    return False
                seen.add(tx["id"])
        return True

    def lookup_transaction(self, transaction_id: str) -> dict | None:
        for block in self.chain:
            for tx in block.transactions:
                if tx["id"] == transaction_id:
                    return {
                        "transaction": deepcopy(tx),
                        "block_index": block.index,
                        "block_hash": block.hash,
                        "confirmations": len(self.chain) - block.index,
                    }
        return None

    def verify_inclusion(self, transaction_id: str) -> bool:
        return self.verify_chain() and self.lookup_transaction(transaction_id) is not None
