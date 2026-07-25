"""Port Destiny Eleven save codec (v1.<checksum>.<btoa(xor)>)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

SALT = "d11\u00b75c3n3\u00b7k3y\u00b7v1\u00b72026"  # _0x3ddada(0x155)


def _imul(a: int, b: int) -> int:
    return (a * b) & 0xFFFFFFFF


def seed_from_salt(salt: str = SALT) -> int:
    """_0x116d9b — hash first 0x15 chars of salt."""
    s = 0
    for i in range(0x15):
        s = (_imul(s, 0x83) + ord(salt[i])) & 0xFFFFFFFF
    return (s & 0xFFFFFFFF) or 1


def xor_stream(data: bytes, salt: str = SALT) -> bytes:
    """_0x2e4096 — symmetric stream XOR (JS string char codes 0-255)."""
    state = seed_from_salt(salt)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        x = _imul(state ^ (state >> 15), 1 | state)
        x = (x + _imul(x ^ (x >> 7), 0x3D | x) ^ x) & 0xFFFFFFFF
        key = ((x ^ (x >> 14)) & 0xFFFFFFFF) & 0xFF
        out[i] = b ^ key
    return bytes(out)


def checksum(text: str, salt: str = SALT) -> str:
    """_0x933e26 — murmur-like hash → base36."""
    seed = seed_from_salt(salt)
    s = text + salt
    h1 = (0xDEADBEEF ^ seed) & 0xFFFFFFFF
    h2 = (0x41C6CE57 ^ seed) & 0xFFFFFFFF
    for ch in s:
        c = ord(ch)
        h1 = _imul(h1 ^ c, 0x9E3779B1)
        h2 = _imul(h2 ^ c, 0x5F356495)
    h1 = _imul(h1 ^ (h1 >> 16), 0x85EBCA6B) ^ _imul(h2 ^ (h2 >> 13), 0xC2B2AE35)
    h2 = _imul(h2 ^ (h2 >> 16), 0x85EBCA6B) ^ _imul(h1 ^ (h1 >> 13), 0xC2B2AE35)
    n = (0x100000000 * (0x1FFFFF & h2)) + (h1 & 0xFFFFFFFF)
    return _to_base36(n)


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    neg = n < 0
    n = abs(n)
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(digits[r])
    s = "".join(reversed(out))
    return "-" + s if neg else s


def encode_save(obj: dict, salt: str = SALT) -> str:
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    cipher = xor_stream(text.encode("utf-8"), salt)
    return "v1." + checksum(text, salt) + "." + base64.b64encode(cipher).decode("ascii")


def decode_save(raw: str, salt: str = SALT) -> dict | None:
    if not raw:
        return None
    if not raw.startswith("v1."):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    # v1.<checksum>.<b64>
    # checksum itself may contain no dots; find 3rd segment start = index of '.' after checksum
    # JS: indexOf('.', 3) — first '.' at or after index 3
    dot = raw.find(".", 3)
    if dot < 0:
        return None
    chk = raw[3:dot]
    b64 = raw[dot + 1 :]
    try:
        cipher = base64.b64decode(b64)
    except Exception:
        return None
    plain_bytes = xor_stream(cipher, salt)
    # JS: decodeURIComponent(escape(xor(...))) — Latin1 bytes → UTF-8 interpret
    try:
        text = plain_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = plain_bytes.decode("latin-1")
    if checksum(text, salt) != chk:
        # still try parse — helpful for debug
        try:
            obj = json.loads(text)
            obj["__checksum_mismatch"] = True
            obj["__expected"] = chk
            obj["__got"] = checksum(text, salt)
            return obj
        except json.JSONDecodeError:
            return {"__fail": "checksum", "expected": chk, "got": checksum(text, salt), "head": text[:80]}
    return json.loads(text)


def main():
    sample = {
        "v": 1,
        "ts": 1700000000000,
        "g": {
            "age": 18,
            "stats": {"t": 60, "p": 55, "m": 58, "c": 50},
            "rep": 20,
            "form": 70,
            "moral": 65,
            "injuryWeeks": 0,
            "potCap": 88,
        },
    }
    enc = encode_save(sample)
    dec = decode_save(enc)
    ok = dec == sample
    print("seed", seed_from_salt())
    print("roundtrip", ok)
    if not ok:
        print(json.dumps(dec, ensure_ascii=True)[:500])


if __name__ == "__main__":
    main()
