#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Свой msgpack-кодек для .set, воспроизводящий исходные байты (float32 -> 0xca, float64 -> 0xcb).

decode(bytes) -> дерево (dict/list/str/bytes/int/float/F64/bool/None/Ext)
encode(tree)  -> bytes;  encode(decode(x)) == x проверяется selftest()/verify_roundtrip.

float по умолчанию пишется как float32 (0xca). Для исходных float64 используется F64.
Нужен, чтобы ДОБАВЛЯТЬ объекты в сцену (set_repack умеет только менять числа).
"""
import struct, os, sys, uuid


class F64(float):
    pass


class Ext:
    def __init__(self, code, data):
        self.code, self.data = code, data

    def __repr__(self):
        return 'Ext(%d,%s)' % (self.code, self.data.hex())


def decode(buf, start=0):
    i = [start]

    def rd(n):
        v = buf[i[0]:i[0] + n]
        assert len(v) == n, 'обрыв данных'
        i[0] += n
        return v

    def val():
        c = rd(1)[0]
        if c <= 0x7f: return c
        if c >= 0xe0: return c - 256
        if 0x80 <= c <= 0x8f: return dict(pair() for _ in range(c & 0x0f))
        if 0x90 <= c <= 0x9f: return [val() for _ in range(c & 0x0f)]
        if 0xa0 <= c <= 0xbf: return rd(c & 0x1f).decode('utf-8')
        if c == 0xc0: return None
        if c == 0xc2: return False
        if c == 0xc3: return True
        if c == 0xc4: return bytes(rd(rd(1)[0]))
        if c == 0xc5: return bytes(rd(struct.unpack('>H', rd(2))[0]))
        if c == 0xc6: return bytes(rd(struct.unpack('>I', rd(4))[0]))
        if c == 0xca: return struct.unpack('>f', rd(4))[0]
        if c == 0xcb: return F64(struct.unpack('>d', rd(8))[0])
        if c == 0xcc: return rd(1)[0]
        if c == 0xcd: return struct.unpack('>H', rd(2))[0]
        if c == 0xce: return struct.unpack('>I', rd(4))[0]
        if c == 0xcf: return struct.unpack('>Q', rd(8))[0]
        if c == 0xd0: return struct.unpack('>b', rd(1))[0]
        if c == 0xd1: return struct.unpack('>h', rd(2))[0]
        if c == 0xd2: return struct.unpack('>i', rd(4))[0]
        if c == 0xd3: return struct.unpack('>q', rd(8))[0]
        if c == 0xd9: return rd(rd(1)[0]).decode('utf-8')
        if c == 0xda: return rd(struct.unpack('>H', rd(2))[0]).decode('utf-8')
        if c == 0xdb: return rd(struct.unpack('>I', rd(4))[0]).decode('utf-8')
        if c == 0xdc: return [val() for _ in range(struct.unpack('>H', rd(2))[0])]
        if c == 0xdd: return [val() for _ in range(struct.unpack('>I', rd(4))[0])]
        if c == 0xde: return dict(pair() for _ in range(struct.unpack('>H', rd(2))[0]))
        if c == 0xdf: return dict(pair() for _ in range(struct.unpack('>I', rd(4))[0]))
        if c in (0xd4, 0xd5, 0xd6, 0xd7, 0xd8):
            n = {0xd4: 1, 0xd5: 2, 0xd6: 4, 0xd7: 8, 0xd8: 16}[c]
            t = struct.unpack('>b', rd(1))[0]
            return Ext(t, bytes(rd(n)))
        if c in (0xc7, 0xc8, 0xc9):
            n = {0xc7: lambda: rd(1)[0], 0xc8: lambda: struct.unpack('>H', rd(2))[0],
                 0xc9: lambda: struct.unpack('>I', rd(4))[0]}[c]()
            t = struct.unpack('>b', rd(1))[0]
            return Ext(t, bytes(rd(n)))
        raise ValueError('неизвестный код 0x%02x на %d' % (c, i[0] - 1))

    def pair():
        k = val()
        return k, val()

    v = val()
    return v, i[0]


def encode(v):
    out = bytearray()

    def w(x):
        if x is None: out.append(0xc0)
        elif x is True: out.append(0xc3)
        elif x is False: out.append(0xc2)
        elif isinstance(x, F64): out.append(0xcb); out.extend(struct.pack('>d', x))
        elif isinstance(x, float): out.append(0xca); out.extend(struct.pack('>f', x))
        elif isinstance(x, int):
            if 0 <= x <= 0x7f: out.append(x)
            elif -32 <= x < 0: out.append(x & 0xff)
            elif 0 <= x <= 0xff: out.extend(b'\xcc' + bytes([x]))
            elif 0 <= x <= 0xffff: out.extend(b'\xcd' + struct.pack('>H', x))
            elif 0 <= x <= 0xffffffff: out.extend(b'\xce' + struct.pack('>I', x))
            elif x > 0: out.extend(b'\xcf' + struct.pack('>Q', x))
            elif x >= -128: out.extend(b'\xd0' + struct.pack('>b', x))
            elif x >= -32768: out.extend(b'\xd1' + struct.pack('>h', x))
            elif x >= -2**31: out.extend(b'\xd2' + struct.pack('>i', x))
            else: out.extend(b'\xd3' + struct.pack('>q', x))
        elif isinstance(x, str):
            b = x.encode('utf-8'); n = len(b)
            if n <= 31: out.append(0xa0 | n)
            elif n <= 0xff: out.extend(b'\xd9' + bytes([n]))
            elif n <= 0xffff: out.extend(b'\xda' + struct.pack('>H', n))
            else: out.extend(b'\xdb' + struct.pack('>I', n))
            out.extend(b)
        elif isinstance(x, (bytes, bytearray)):
            n = len(x)
            if n <= 0xff: out.extend(b'\xc4' + bytes([n]))
            elif n <= 0xffff: out.extend(b'\xc5' + struct.pack('>H', n))
            else: out.extend(b'\xc6' + struct.pack('>I', n))
            out.extend(x)
        elif isinstance(x, (list, tuple)):
            n = len(x)
            if n <= 15: out.append(0x90 | n)
            elif n <= 0xffff: out.extend(b'\xdc' + struct.pack('>H', n))
            else: out.extend(b'\xdd' + struct.pack('>I', n))
            for e in x: w(e)
        elif isinstance(x, dict):
            n = len(x)
            if n <= 15: out.append(0x80 | n)
            elif n <= 0xffff: out.extend(b'\xde' + struct.pack('>H', n))
            else: out.extend(b'\xdf' + struct.pack('>I', n))
            for k, e in x.items(): w(k); w(e)
        elif isinstance(x, Ext):
            n = len(x.data)
            fixed = {1: 0xd4, 2: 0xd5, 4: 0xd6, 8: 0xd7, 16: 0xd8}
            if n in fixed: out.append(fixed[n])
            elif n <= 0xff: out.extend(b'\xc7' + bytes([n]))
            elif n <= 0xffff: out.extend(b'\xc8' + struct.pack('>H', n))
            else: out.extend(b'\xc9' + struct.pack('>I', n))
            out.extend(struct.pack('>b', x.code)); out.extend(x.data)
        else:
            raise TypeError(type(x))

    w(v)
    return bytes(out)


def new_id():
    return uuid.uuid4().bytes


def load_set(path):
    raw = open(path, 'rb').read()
    tree, end = decode(raw, 20)
    assert end == len(raw), 'payload разобран не до конца'
    return raw[:20], tree


def load_bytes(raw):
    tree, end = decode(raw, 20)
    assert end == len(raw), 'payload разобран не до конца'
    return raw[:20], tree


def dump_bytes(header, tree):
    import set_checksum
    payload = encode(tree)
    h = bytearray(header)
    struct.pack_into('<I', h, 8, len(payload))
    return set_checksum.fix_bytes(bytes(h) + payload)


def save_set(path, header, tree):
    with open(path, 'wb') as fh:
        fh.write(dump_bytes(header, tree))


def verify_roundtrip(path):
    raw = open(path, 'rb').read()
    tree, end = decode(raw, 20)
    return end == len(raw) and encode(tree) == raw[20:]


if __name__ == '__main__':
    for p in sys.argv[1:]:
        try:
            print('%s  %s' % ('OK  ' if verify_roundtrip(p) else 'FAIL', os.path.basename(p)))
        except Exception as e:
            print('ERR ', os.path.basename(p), e)
