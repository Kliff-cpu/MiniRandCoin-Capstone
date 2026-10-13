import hashlib
import json
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def address_from_public_key(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()[:40]


@dataclass
class Wallet:
    label: str
    pk: str = field(init=False)
    address: str = field(init=False)
    _private_key: ec.EllipticCurvePrivateKey = field(init=False, repr=False)

    def __post_init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256K1())
        numbers = self._private_key.public_key().public_numbers()
        self.pk = (numbers.x.to_bytes(32, "big") +
                   numbers.y.to_bytes(32, "big")).hex()
        self.address = address_from_public_key(self.pk)

    @property
    def public_key_hex(self) -> str:
        return self.pk

    def sign_payload(self, payload: dict) -> str:
        signature = self._private_key.sign(
            canonical_payload(payload), ec.ECDSA(hashes.SHA256())
        )
        return signature.hex()

    @staticmethod
    def verify_payload(payload: dict, signature_hex: str,
                       public_key_hex: str) -> bool:
        try:
            key_bytes = b"\x04" + bytes.fromhex(public_key_hex)
            public_key = ec.EllipticCurvePublicKey.from_encoded_point(
                ec.SECP256K1(), key_bytes
            )
            public_key.verify(
                bytes.fromhex(signature_hex),
                canonical_payload(payload),
                ec.ECDSA(hashes.SHA256()),
            )
            return True
        except (ValueError, InvalidSignature, TypeError):
            return False

    def public_info(self) -> dict:
        return {
            "label": self.label,
            "address": self.address,
            "public_key_hex": self.pk,
        }


def create_wallets() -> tuple[Wallet, Wallet, Wallet]:
    return Wallet("Sender"), Wallet("Recipient"), Wallet("ReserveAgent")
