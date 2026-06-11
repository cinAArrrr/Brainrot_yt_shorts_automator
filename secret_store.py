"""
secret_store.py -- Passphrase-encrypted storage for BrainRot Bot secrets.

Encrypts files like ``config.json`` and ``cookies.txt`` at rest so they can be
kept on disk (and even shared as part of a zip) without leaking the API key or
your YouTube session cookies in plaintext.

Format on disk (single line, ASCII):

    $BR1$<salt_hex>$<fernet_token>

* ``BR1``           -- format version magic
* ``salt_hex``      -- 16 random bytes, hex-encoded, fresh per file
* ``fernet_token``  -- Fernet (AES-128-CBC + HMAC-SHA256) ciphertext of the
                       plaintext bytes. The Fernet key is derived from the
                       user's passphrase via PBKDF2-HMAC-SHA256 with 200,000
                       iterations and the per-file salt.

Use the ``encrypt_path`` / ``decrypt_path`` helpers to convert files in place
between plaintext and the encrypted form.
"""

from __future__ import annotations

import base64
import getpass
import os
import secrets
from pathlib import Path
from typing import Optional, Union

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


MAGIC = "BR1"
SALT_BYTES = 16
PBKDF2_ITERATIONS = 200_000

_CACHED_PASSPHRASE: Optional[str] = None


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from a passphrase + per-file salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def encrypt_bytes(plaintext: bytes, passphrase: str) -> str:
    """Encrypt arbitrary bytes -> ASCII-safe single-line token."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive_key(passphrase, salt)
    token = Fernet(key).encrypt(plaintext).decode("ascii")
    return f"${MAGIC}${salt.hex()}${token}"


def decrypt_bytes(blob: str, passphrase: str) -> bytes:
    """Inverse of ``encrypt_bytes``. Raises ``ValueError`` on any error."""
    blob = blob.strip()
    if not blob.startswith(f"${MAGIC}$"):
        raise ValueError(
            f"Not a BrainRot encrypted blob (expected ${MAGIC}$ prefix)."
        )
    parts = blob.split("$", 3)
    if len(parts) != 4:
        raise ValueError("Malformed encrypted blob.")
    _, magic, salt_hex, token = parts
    if magic != MAGIC:
        raise ValueError(f"Unsupported format version: {magic}")
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError as e:
        raise ValueError("Salt is not valid hex.") from e

    key = _derive_key(passphrase, salt)
    try:
        return Fernet(key).decrypt(token.encode("ascii"))
    except InvalidToken as e:
        raise ValueError("Wrong passphrase or file is corrupted.") from e


def is_encrypted_file(path: Union[str, Path]) -> bool:
    """Cheap check: does this file look like an encrypted blob we wrote?"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False
    try:
        with open(p, "r", encoding="utf-8") as f:
            head = f.read(64)
    except Exception:
        return False
    return head.lstrip().startswith(f"${MAGIC}$")


def encrypt_path(plain_path: Union[str, Path], enc_path: Union[str, Path], passphrase: str) -> Path:
    """Encrypt a plaintext file and write the result to ``enc_path``."""
    plain_path = Path(plain_path)
    enc_path = Path(enc_path)
    data = plain_path.read_bytes()
    blob = encrypt_bytes(data, passphrase)
    enc_path.write_text(blob, encoding="utf-8")
    try:
        os.chmod(enc_path, 0o600)
    except Exception:
        pass
    return enc_path


def decrypt_path(enc_path: Union[str, Path], passphrase: str) -> bytes:
    """Read an encrypted file from disk and return its plaintext bytes."""
    blob = Path(enc_path).read_text(encoding="utf-8")
    return decrypt_bytes(blob, passphrase)


def get_passphrase(prompt: str = "Passphrase: ", confirm: bool = False) -> str:
    """Resolve a passphrase from cache, env var, or an interactive prompt."""
    global _CACHED_PASSPHRASE

    env_pp = os.environ.get("BRAINROT_PASSPHRASE")
    if env_pp:
        return env_pp

    if not confirm and _CACHED_PASSPHRASE is not None:
        return _CACHED_PASSPHRASE

    while True:
        pp = getpass.getpass(prompt)
        if not pp:
            print("Passphrase cannot be empty.")
            continue
        if confirm:
            again = getpass.getpass("Confirm passphrase: ")
            if pp != again:
                print("Passphrases did not match. Try again.")
                continue
        _CACHED_PASSPHRASE = pp
        return pp


def clear_cached_passphrase() -> None:
    global _CACHED_PASSPHRASE
    _CACHED_PASSPHRASE = None
