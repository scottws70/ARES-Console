"""LZHUF compression as used by FBB / Winlink B2F.

Port of the classic Okumura/Yoshizaki LZHUF with the FBB parameters
(N=2048, F=60, THRESHOLD=2).  The B2 variant prefixes the stream with a
CRC-16 of the compressed data (size header + Huffman stream).
"""

N = 2048
F = 60
THRESHOLD = 2
N_CHAR = 256 - THRESHOLD + F  # 314
T = N_CHAR * 2 - 1            # 627
R = T - 1
MAX_FREQ = 0x8000

P_LEN = [
    3, 4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
]
P_CODE = [
    0x00, 0x20, 0x30, 0x40, 0x50, 0x58, 0x60, 0x68, 0x70, 0x78, 0x80, 0x88, 0x90, 0x94, 0x98, 0x9C,
    0xA0, 0xA4, 0xA8, 0xAC, 0xB0, 0xB4, 0xB8, 0xBC, 0xC0, 0xC2, 0xC4, 0xC6, 0xC8, 0xCA, 0xCC, 0xCE,
    0xD0, 0xD2, 0xD4, 0xD6, 0xD8, 0xDA, 0xDC, 0xDE, 0xE0, 0xE2, 0xE4, 0xE6, 0xE8, 0xEA, 0xEC, 0xEE,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
]

# Decode tables derived from the encode tables.
D_CODE = [0] * 256
D_LEN = [0] * 256
for _i in range(64):
    _span = 1 << (8 - P_LEN[_i])
    for _v in range(P_CODE[_i], P_CODE[_i] + _span):
        D_CODE[_v] = _i
        D_LEN[_v] = P_LEN[_i]
assert all(D_LEN), "lzhuf decode table incomplete"


class _Huff:
    def __init__(self):
        self.freq = [0] * (T + 1)
        self.prnt = [0] * (T + N_CHAR)
        self.son = [0] * T
        freq, prnt, son = self.freq, self.prnt, self.son
        for i in range(N_CHAR):
            freq[i] = 1
            son[i] = i + T
            prnt[i + T] = i
        i, j = 0, N_CHAR
        while j <= R:
            freq[j] = freq[i] + freq[i + 1]
            son[j] = i
            prnt[i] = prnt[i + 1] = j
            i += 2
            j += 1
        freq[T] = 0xFFFF
        prnt[R] = 0

    def reconst(self):
        freq, prnt, son = self.freq, self.prnt, self.son
        j = 0
        for i in range(T):
            if son[i] >= T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, N_CHAR
        while j < T:
            k = i + 1
            f = freq[i] + freq[k]
            freq[j] = f
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(T):
            k = son[i]
            if k >= T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(self, c):
        freq, prnt, son = self.freq, self.prnt, self.son
        if freq[R] == MAX_FREQ:
            self.reconst()
        c = prnt[c + T]
        while True:
            freq[c] += 1
            k = freq[c]
            l = c + 1
            if k > freq[l]:
                l += 1
                while k > freq[l]:
                    l += 1
                l -= 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break


class _BitWriter:
    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, nbits, value16):
        """Write the top `nbits` bits of a 16-bit value."""
        for b in range(nbits):
            self.acc = (self.acc << 1) | ((value16 >> (15 - b)) & 1)
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                self.acc = 0
                self.n = 0

    def put_bits(self, bits):
        for bit in bits:
            self.acc = (self.acc << 1) | bit
            self.n += 1
            if self.n == 8:
                self.out.append(self.acc)
                self.acc = 0
                self.n = 0

    def flush(self):
        if self.n:
            self.out.append((self.acc << (8 - self.n)) & 0xFF)
            self.acc = 0
            self.n = 0


class _BitReader:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos
        self.acc = 0
        self.n = 0

    def bit(self):
        if self.n == 0:
            self.acc = self.data[self.pos] if self.pos < len(self.data) else 0
            self.pos += 1
            self.n = 8
        self.n -= 1
        return (self.acc >> self.n) & 1

    def byte(self):
        v = 0
        for _ in range(8):
            v = (v << 1) | self.bit()
        return v


def _encode_char(h, w, c):
    bits = []
    k = h.prnt[c + T]
    while True:
        bits.append(k & 1)
        k = h.prnt[k]
        if k == R:
            break
    bits.reverse()
    w.put_bits(bits)
    h.update(c)


def _encode_position(w, c):
    i = c >> 6
    w.put(P_LEN[i], P_CODE[i] << 8)
    w.put(6, (c & 0x3F) << 10)


def compress(data: bytes) -> bytes:
    """Compress with plain LZHUF (4-byte little-endian size header)."""
    data = bytes(data)
    n = len(data)
    w = _BitWriter()
    w.out += n.to_bytes(4, "little")
    if n == 0:
        return bytes(w.out)
    h = _Huff()
    chains = {}
    max_dist = N - F
    r = N - F  # decoder ring position, kept in sync
    pos = 0
    while pos < n:
        best_len, best_dist = 0, 0
        if pos + 2 < n:
            key = data[pos:pos + 3]
            cand = chains.get(key)
            if cand:
                limit = min(F, n - pos)
                tries = 0
                for p in reversed(cand):
                    d = pos - p
                    if d > max_dist:
                        break
                    l = 3
                    while l < limit and data[p + l] == data[pos + l]:
                        l += 1
                    if l > best_len:
                        best_len, best_dist = l, d
                        if l == limit:
                            break
                    tries += 1
                    if tries > 96:
                        break
        if best_len > THRESHOLD:
            _encode_char(h, w, 255 - THRESHOLD + best_len)
            src = (r - best_dist) & (N - 1)
            _encode_position(w, (r - src - 1) & (N - 1))
            step = best_len
        else:
            _encode_char(h, w, data[pos])
            step = 1
        for q in range(pos, pos + step):
            if q + 2 < n:
                k = data[q:q + 3]
                lst = chains.get(k)
                if lst is None:
                    chains[k] = [q]
                else:
                    lst.append(q)
                    if len(lst) > 256:
                        del lst[:128]
        pos += step
        r = (r + step) & (N - 1)
    w.flush()
    return bytes(w.out)


def decompress(data: bytes) -> bytes:
    """Decompress plain LZHUF data (with 4-byte size header)."""
    if len(data) < 4:
        raise ValueError("lzhuf: short data")
    size = int.from_bytes(data[:4], "little")
    if size == 0:
        return b""
    if size > 50 * 1024 * 1024:
        raise ValueError("lzhuf: implausible size")
    h = _Huff()
    rd = _BitReader(data, 4)
    buf = bytearray(b" " * N)
    r = N - F
    out = bytearray()
    son = h.son
    while len(out) < size:
        c = son[R]
        while c < T:
            c += rd.bit()
            c = son[c]
        c -= T
        h.update(c)
        if c < 256:
            out.append(c)
            buf[r] = c
            r = (r + 1) & (N - 1)
        else:
            i = rd.byte()
            cc = D_CODE[i] << 6
            j = D_LEN[i] - 2
            while j > 0:
                i = (i << 1) + rd.bit()
                j -= 1
            pos = cc | (i & 0x3F)
            i = (r - pos - 1) & (N - 1)
            j = c - 255 + THRESHOLD
            for k in range(j):
                b = buf[(i + k) & (N - 1)]
                out.append(b)
                buf[r] = b
                r = (r + 1) & (N - 1)
        if rd.pos > len(data) + 4:
            raise ValueError("lzhuf: truncated data")
    return bytes(out[:size])


# ---- CRC16 (CCITT/XMODEM) as used by FBB B2 compression ----
_CRC_TABLE = []
for _n in range(256):
    _c = _n << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) if (_c & 0x8000) else (_c << 1)
    _CRC_TABLE.append(_c & 0xFFFF)


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def compress_b2(data: bytes) -> bytes:
    body = compress(data)
    crc = crc16(body)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF]) + body


def decompress_b2(data: bytes) -> bytes:
    if len(data) < 6:
        raise ValueError("b2: short data")
    body = data[2:]
    crc = crc16(body)
    got_le = data[0] | (data[1] << 8)
    got_be = (data[0] << 8) | data[1]
    if crc not in (got_le, got_be):
        raise ValueError("b2: CRC mismatch")
    return decompress(body)
