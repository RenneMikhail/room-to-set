"""set.a.light 3D V3 `.set` file checksum.

VARIANT : MurmurHash3 x86_128 / "x64_128" (the canonical 128-bit MurmurHash3),
          folded to 32 bits as  (h1 ^ h2) & 0xffffffff.
SEED    : 0
RANGE   : the msgpack payload, i.e. file bytes [20:]  (byte range 20 .. EOF)
STORED  : file offset 12, uint32 little-endian.

Reverse-engineered from the arm64 GameAssembly of set.a.light 3D V3:

  SAL.SALFileReader.ReadContent @ RVA 0xED2A08
      0xED2BC0: x0 = buffer, x1 = len, w2 = 0 (start)
      0xED2BCC: x3 = w23 (count)      0xED2BD0: w4 = 0 (seed)
      0xED2BD8: bl SAL.Util$$MurmurHash3  (RVA 0xED7970)
      0xED2BDC: ldr w8,[x20,#0x30]  ; contentChecksum   cmp w8,w0

  SAL.Util$$MurmurHash3(span,start,count,seed) @ RVA 0xED7970
      forwards to SAL.Util.BurstHelper$$MurmurHash3Impl (RVA 0xEEE214)
      which tail-branches to ...$BurstManaged (RVA 0xEEE508):
      0xEEE524: bl SAL.MurmurHash3$$MurmurHash3_x64_128_Impl (RVA 0xEC4AF4)
      0xEEE52C: eor x0, x9, x8     <-- h1 ^ h2, low word compared

  SAL.MurmurHash3$$MurmurHash3_x64_128_Impl @ RVA 0xEC4AF4 contains
      c1 = 0x87c37b91114253d5, c2 = 0x4cf5ad432745937f,
      fmix64 = 0xff51afd7ed558ccd / 0xc4ceb9fe1a85ec53
      and stores h1 -> [x3], h2 -> [x4].
"""

from __future__ import annotations

import os
import struct

MASK64 = (1 << 64) - 1
C1 = 0x87C37B91114253D5
C2 = 0x4CF5AD432745937F

HEADER_SIZE = 20          # 'SALS' magic + 16 bytes of header words
CHECKSUM_OFFSET = 12      # uint32 LE, inside the header


def _rotl64(x: int, r: int) -> int:
    return ((x << r) | (x >> (64 - r))) & MASK64


def _fmix64(k: int) -> int:
    k &= MASK64
    k ^= k >> 33
    k = (k * 0xFF51AFD7ED558CCD) & MASK64
    k ^= k >> 33
    k = (k * 0xC4CEB9FE1A85EC53) & MASK64
    k ^= k >> 33
    return k


def murmur3_x64_128(data: bytes, seed: int = 0):
    """Canonical MurmurHash3 128-bit (the x64 variant). Returns (h1, h2)."""
    length = len(data)
    nblocks = length // 16
    h1 = h2 = seed & MASK64

    for i in range(nblocks):
        k1, k2 = struct.unpack_from("<QQ", data, i * 16)
        k1 = (k1 * C1) & MASK64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * C2) & MASK64
        h1 ^= k1
        h1 = _rotl64(h1, 27)
        h1 = (h1 + h2) & MASK64
        h1 = (h1 * 5 + 0x52DCE729) & MASK64

        k2 = (k2 * C2) & MASK64
        k2 = _rotl64(k2, 33)
        k2 = (k2 * C1) & MASK64
        h2 ^= k2
        h2 = _rotl64(h2, 31)
        h2 = (h2 + h1) & MASK64
        h2 = (h2 * 5 + 0x38495AB5) & MASK64

    tail = data[nblocks * 16:]
    k1 = k2 = 0
    for j in range(len(tail) - 1, -1, -1):
        b = tail[j]
        if j >= 8:
            k2 ^= b << ((j - 8) * 8)
        else:
            k1 ^= b << (j * 8)

    if len(tail) > 8:
        k2 = (k2 * C2) & MASK64
        k2 = _rotl64(k2, 33)
        k2 = (k2 * C1) & MASK64
        h2 ^= k2
    if len(tail) > 0:
        k1 = (k1 * C1) & MASK64
        k1 = _rotl64(k1, 31)
        k1 = (k1 * C2) & MASK64
        h1 ^= k1

    h1 ^= length
    h2 ^= length
    h1 = (h1 + h2) & MASK64
    h2 = (h2 + h1) & MASK64
    h1 = _fmix64(h1)
    h2 = _fmix64(h2)
    h1 = (h1 + h2) & MASK64
    h2 = (h2 + h1) & MASK64
    return h1, h2


def checksum_of_payload(payload: bytes, seed: int = 0) -> int:
    """`contentChecksum` for a raw msgpack payload."""
    h1, h2 = murmur3_x64_128(payload, seed)
    return (h1 ^ h2) & 0xFFFFFFFF


def compute(data: bytes, seed: int = 0) -> int:
    """Return the correct `contentChecksum` for a whole `.set` file's bytes.

    Scope: single-entry containers, where `payloadLen` (u32 @ 8) equals
    `len(data) - 20`. Verified byte-exact on real files (see __main__).
    For multi-entry containers this raises ValueError instead of guessing.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("file too short to be a .set container")
    if data[:4] != b"SALS":
        raise ValueError("bad magic: expected b'SALS'")

    payload_len, _, entry_count = struct.unpack_from("<III", data, 8)
    if entry_count != 0 or payload_len != len(data) - HEADER_SIZE:
        raise ValueError(
            "multi-entry / trailing-blob .set container (entries=%d, payloadLen=%d, "
            "size-20=%d): checksum range not yet determined"
            % (entry_count, payload_len, len(data) - HEADER_SIZE)
        )
    return checksum_of_payload(data[HEADER_SIZE:], seed)


def stored_checksum(data: bytes) -> int:
    """The checksum value currently written at offset 12."""
    return struct.unpack_from("<I", data, CHECKSUM_OFFSET)[0]


def verify(data: bytes) -> bool:
    """True when the stored checksum matches a freshly computed one."""
    return stored_checksum(data) == compute(data)


def fix_bytes(data: bytes) -> bytes:
    """Return `data` with the stored checksum at offset 12 corrected."""
    new = compute(data)
    out = bytearray(data)
    struct.pack_into("<I", out, CHECKSUM_OFFSET, new)
    return bytes(out)


def fix_file(path, backup: bool = False) -> int:
    """Rewrite the stored checksum in place. Returns the new checksum.

    Pass backup=True to keep a `.bak` copy next to the original.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    fixed = fix_bytes(data)
    if backup:
        with open(path + ".bak", "wb") as fh:
            fh.write(data)
    with open(path, "wb") as fh:
        fh.write(fixed)
    return stored_checksum(fixed)


# --------------------------------------------------------------------------
# Self-test: asserts an exact match against real files.
# --------------------------------------------------------------------------
_TEST_FILES = [
    "/Users/misharenne/Downloads/Project-2603231337 (5).set",
    "/Users/misharenne/Downloads/result.set",
]

# Known-good pairs (checksum stored at offset 12) for files that may not exist
# on every machine: size -> expected checksum.
_KNOWN = {
    19345: 0x34411D97,
    32071: 0x74BE70A3,
    72506: 0xB438AEF1,
    18593: 0xED9B0483,
    59089: 0x1E37E009,
    28599: 0x0AE2CCA8,
    19746: 0x389809D7,
}


def _selftest() -> int:
    rc = 0
    tested = 0
    for path in _TEST_FILES:
        if not os.path.exists(path):
            print("SKIP (missing): %s" % path)
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        stored = stored_checksum(data)
        calc = compute(data)
        ok = stored == calc
        tested += 1
        rc |= 0 if ok else 1
        print(
            "%-42s len=%6d stored@12=%#010x computed=%#010x  %s"
            % (os.path.basename(path), len(data), stored, calc, "PASS" if ok else "FAIL")
        )
        assert ok, "checksum mismatch for %s" % path

    # Cross-check the same files against the size table, and re-verify after
    # a round trip through fix_bytes (idempotence).
    for path in _TEST_FILES:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        exp = _KNOWN.get(len(data))
        if exp is not None:
            assert stored_checksum(data) == exp, "size table mismatch for %s" % path
        assert fix_bytes(data) == data, "fix_bytes is not idempotent for %s" % path
        # corrupting a payload byte must change the computed checksum
        if len(data) > HEADER_SIZE:
            bad = bytearray(data)
            bad[HEADER_SIZE] ^= 0x01
            assert compute(bytes(bad)) != stored_checksum(data), "checksum too weak"
    print("selftest OK (%d file(s) verified)" % tested)
    return rc


if __name__ == "__main__":
    raise SystemExit(_selftest())
