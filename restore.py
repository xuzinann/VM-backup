#!/usr/bin/env python3
"""Verify and decrypt a migration backup. Never activates services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def decrypt(assets, manifest, key_path, output):
    key = bytes.fromhex(key_path.read_text().strip())
    if len(key) != 32:
        raise ValueError("Expected a 256-bit hexadecimal key")
    for chunk in manifest["chunks"]:
        path = assets / chunk["name"]
        h = hashlib.sha256()
        with path.open("rb") as f:
            while block := f.read(4 * 1024 * 1024):
                h.update(block)
        if path.stat().st_size != chunk["size"] or h.hexdigest() != chunk["sha256"]:
            raise ValueError(f"Checksum mismatch: {path.name}")
    decryptor = Cipher(algorithms.AES(key), modes.GCM(
        bytes.fromhex(manifest["nonce"]), bytes.fromhex(manifest["tag"])
    )).decryptor()
    decryptor.authenticate_additional_data(b"VM-backup-format-v1")
    partial = output.with_name(output.name + ".partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as dst:
            for chunk in manifest["chunks"]:
                with (assets / chunk["name"]).open("rb") as src:
                    while block := src.read(4 * 1024 * 1024):
                        dst.write(decryptor.update(block))
            dst.write(decryptor.finalize())
        if output.exists():
            raise FileExistsError(output)
        partial.rename(output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--check-tar", action="store_true")
    a = p.parse_args()
    manifest = json.loads((a.assets / "manifest.json").read_text())
    decrypt(a.assets, manifest, a.key, a.output)
    if a.check_tar:
        subprocess.run(["tar", "-tzf", str(a.output)], stdout=subprocess.DEVNULL, check=True)
    print("Checksums and AES-GCM authentication passed.")
    print(f"Decrypted archive: {a.output}")
    print("Extract into a staging directory. Do not overwrite a running VM's root filesystem.")


if __name__ == "__main__":
    main()
