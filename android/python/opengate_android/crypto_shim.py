# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-stdlib SHA-256 fallback shim for vendored MIT sony-pmca-re on Chaquopy.

``pmca/usb/sony.py`` imports ``Cryptodome.Hash.SHA256`` (falling back to
``Crypto.Hash.SHA256``) and calls ``SHA256.new(data).digest()``. Building native
``pycryptodomex`` wheels on Android is unnecessary because Python's standard
library ``hashlib.sha256`` already provides an identical interface.
"""
from __future__ import annotations

import hashlib
import sys
import types
from typing import Any

_SHIM_MARKER = "_OPENGATE_CRYPTO_SHIM"


class StdlibSHA256Hash:
    """Drop-in replacement for ``Cryptodome.Hash.SHA256.SHA256Hash``."""

    digest_size: int = 32
    block_size: int = 64
    oid: str = "2.16.840.1.101.3.4.2.1"

    def __init__(self, data: bytes | bytearray | memoryview = b"") -> None:
        self._hasher = hashlib.sha256()
        if data:
            self.update(data)

    def update(self, data: bytes | bytearray | memoryview) -> None:
        self._hasher.update(bytes(data))

    def digest(self) -> bytes:
        return self._hasher.digest()

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()

    def copy(self) -> StdlibSHA256Hash:
        cloned = StdlibSHA256Hash()
        cloned._hasher = self._hasher.copy()
        return cloned


def _build_sha256_module(full_name: str) -> types.ModuleType:
    mod = types.ModuleType(full_name)
    mod.digest_size = 32  # type: ignore[attr-defined]
    mod.block_size = 64  # type: ignore[attr-defined]
    mod.SHA256Hash = StdlibSHA256Hash  # type: ignore[attr-defined]

    def new(data: bytes | bytearray | memoryview = b"") -> StdlibSHA256Hash:
        return StdlibSHA256Hash(data)

    mod.new = new  # type: ignore[attr-defined]
    setattr(mod, _SHIM_MARKER, True)
    return mod


def _register_namespace(root_pkg: str) -> None:
    hash_pkg = f"{root_pkg}.Hash"
    sha_pkg = f"{hash_pkg}.SHA256"

    root_mod = types.ModuleType(root_pkg)
    root_mod.__path__ = []  # type: ignore[attr-defined]
    setattr(root_mod, _SHIM_MARKER, True)

    hash_mod = types.ModuleType(hash_pkg)
    hash_mod.__path__ = []  # type: ignore[attr-defined]
    setattr(hash_mod, _SHIM_MARKER, True)

    sha_mod = _build_sha256_module(sha_pkg)

    hash_mod.SHA256 = sha_mod  # type: ignore[attr-defined]
    root_mod.Hash = hash_mod  # type: ignore[attr-defined]

    sys.modules[root_pkg] = root_mod
    sys.modules[hash_pkg] = hash_mod
    sys.modules[sha_pkg] = sha_mod


def install_cryptodome_sha256_fallback(*, force: bool = False) -> bool:
    """Register stdlib ``Cryptodome.Hash.SHA256`` if ``Cryptodome`` is unavailable.

    Returns ``True`` if the fallback shim was installed, or ``False`` if a real
    ``Cryptodome.Hash.SHA256`` module is already importable.
    """
    if not force:
        try:
            from Cryptodome.Hash import SHA256 as existing  # type: ignore[import-not-found]

            if hasattr(existing, "new") and not getattr(existing, _SHIM_MARKER, False):
                return False
            if getattr(existing, _SHIM_MARKER, False):
                return True
        except ImportError:
            pass

    _register_namespace("Cryptodome")
    return True


def uninstall_cryptodome_sha256_fallback() -> None:
    """Remove shim-installed ``Cryptodome`` modules from ``sys.modules``."""
    for name in ("Cryptodome.Hash.SHA256", "Cryptodome.Hash", "Cryptodome"):
        mod: Any = sys.modules.get(name)
        if mod is not None and getattr(mod, _SHIM_MARKER, False):
            sys.modules.pop(name, None)
