"""Fill cells of an existing .xls (BIFF8) workbook while keeping everything else.

The usual Python route (``xlrd`` + ``xlutils.copy`` + ``xlwt``) rebuilds the
workbook and silently drops data-validation dropdowns, cell comments and
drawing objects. The ASYCUDA SAD model relies on those (field hints, lists of
customs offices, length limits), so this module edits the BIFF record stream
directly instead:

* the workbook-globals substream is copied as-is, except that the shared
  string table (SST) is rebuilt with any new strings appended (existing string
  indexes are unchanged, so untouched cells keep pointing at the same text);
* in each sheet only the rows that are written to are re-encoded — every other
  record (formatting, merged cells, column widths, comments, dropdowns,
  drawings, print settings…) is copied byte-for-byte;
* INDEX/DBCELL/EXTSST lookup records are left out; they are optional
  performance hints that Excel, LibreOffice and xlrd rebuild or ignore.

Only what the SAD needs is supported: text, numbers and blanks. Rows that
contain formulas cannot be modified.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field

import olefile
from xlwt.CompoundDoc import XlsDoc

# Record ids
BOF, EOF, BOUNDSHEET, SST, EXTSST, CONTINUE = 0x0809, 0x000A, 0x0085, 0x00FC, 0x00FF, 0x003C
INDEX, DBCELL, DIMENSIONS, ROW = 0x020B, 0x00D7, 0x0200, 0x0208
BLANK, NUMBER, LABEL, BOOLERR, RK, MULRK, MULBLANK, LABELSST = 0x0201, 0x0203, 0x0204, 0x0205, 0x027E, 0x00BD, 0x00BE, 0x00FD
FORMULA, STRING, SHRFMLA, ARRAY, TABLE = 0x0006, 0x0207, 0x04BC, 0x0221, 0x0236

CELL_TABLE = {ROW, BLANK, NUMBER, LABEL, BOOLERR, RK, MULRK, MULBLANK, LABELSST,
              FORMULA, STRING, SHRFMLA, ARRAY, TABLE, DBCELL}
FORMULA_FAMILY = {FORMULA, STRING, SHRFMLA, ARRAY, TABLE}
MAX_RECORD = 8224
DEFAULT_XF = 0x0F


class TemplateError(ValueError):
    pass


def _records(data: bytes, start: int = 0, stop: int | None = None) -> list[tuple[int, bytes]]:
    out, i, n = [], start, len(data) if stop is None else stop
    while i + 4 <= n:
        rt, ln = struct.unpack_from("<HH", data, i)
        out.append((rt, data[i + 4:i + 4 + ln]))
        i += 4 + ln
    return out


def _pack(rt: int, body: bytes) -> bytes:
    return struct.pack("<HH", rt, len(body)) + body


# ── Shared string table ───────────────────────────────────────

def _parse_sst(chunks: list[bytes]) -> list[str]:
    """Decode an SST record plus its CONTINUE records into plain strings."""
    strings: list[str] = []
    ci, pos = 0, 8
    total = struct.unpack_from("<I", chunks[0], 4)[0]

    def read(n: int) -> bytes:
        nonlocal ci, pos
        out = b""
        while n:
            if pos >= len(chunks[ci]):
                ci, pos = ci + 1, 0
            take = min(n, len(chunks[ci]) - pos)
            out += chunks[ci][pos:pos + take]
            pos += take
            n -= take
        return out

    for _ in range(total):
        cch = struct.unpack("<H", read(2))[0]
        flags = read(1)[0]
        runs = struct.unpack("<H", read(2))[0] if flags & 0x08 else 0
        ext = struct.unpack("<I", read(4))[0] if flags & 0x04 else 0
        chars, wide, parts = cch, flags & 0x01, []
        while chars:
            if pos >= len(chunks[ci]):  # character data continues in a CONTINUE record
                ci, pos = ci + 1, 0
                wide = chunks[ci][0] & 0x01
                pos = 1
            width = 2 if wide else 1
            avail = (len(chunks[ci]) - pos) // width
            take = min(chars, avail)
            raw = chunks[ci][pos:pos + take * width]
            parts.append(raw.decode("utf-16-le") if wide else raw.decode("latin-1"))
            pos += take * width
            chars -= take
        read(runs * 4)
        read(ext)
        strings.append("".join(parts))
    return strings


def _build_sst(strings: list[str], total_refs: int) -> list[bytes]:
    """Encode strings as SST + CONTINUE records (UTF-16, no rich text)."""
    records: list[bytearray] = [bytearray(struct.pack("<II", total_refs, len(strings)))]

    def room() -> int:
        return MAX_RECORD - len(records[-1])

    for s in strings:
        data = s.encode("utf-16-le")
        if room() < 3 + 2:  # header (+ at least one char) must not be split
            records.append(bytearray())
        records[-1] += struct.pack("<HB", len(s), 0x01)
        while data:
            take = min(len(data), room() // 2 * 2)
            if take == 0:
                records.append(bytearray(b"\x01"))  # continued character data restates the flags
                continue
            records[-1] += data[:take]
            data = data[take:]
    return [bytes(r) for r in records]


# ── Sheets ────────────────────────────────────────────────────

@dataclass
class _Row:
    record: bytes | None = None            # ROW record body
    cells: list[tuple[int, bytes]] = field(default_factory=list)  # raw records, original order
    expanded: dict[int, tuple[int, bytes]] | None = None          # col -> (rt, body)


@dataclass
class _Sheet:
    name: str
    pre: list[tuple[int, bytes]]
    rows: dict[int, _Row]
    post: list[tuple[int, bytes]]
    col_xf: dict[int, int]

    def row(self, r: int) -> _Row:
        return self.rows.setdefault(r, _Row())


def _cell_row(rt: int, body: bytes) -> int | None:
    if rt in (STRING, DBCELL):
        return None
    return struct.unpack_from("<H", body, 0)[0]


def _expand(row: _Row) -> dict[int, tuple[int, bytes]]:
    if row.expanded is not None:
        return row.expanded
    cells: dict[int, tuple[int, bytes]] = {}
    for rt, body in row.cells:
        if rt in FORMULA_FAMILY:
            raise TemplateError("rows containing formulas cannot be modified")
        r, c = struct.unpack_from("<HH", body, 0)
        if rt == MULBLANK:
            last = struct.unpack_from("<H", body, len(body) - 2)[0]
            for k, col in enumerate(range(c, last + 1)):
                xf = struct.unpack_from("<H", body, 4 + 2 * k)[0]
                cells[col] = (BLANK, struct.pack("<HHH", r, col, xf))
        elif rt == MULRK:
            last = struct.unpack_from("<H", body, len(body) - 2)[0]
            for k, col in enumerate(range(c, last + 1)):
                xf, rk = struct.unpack_from("<HI", body, 4 + 6 * k)
                cells[col] = (RK, struct.pack("<HHHI", r, col, xf, rk))
        else:
            cells[c] = (rt, body)
    row.expanded = cells
    return cells


def _serialize_row_cells(row: _Row) -> bytes:
    if row.expanded is None:
        return b"".join(_pack(rt, body) for rt, body in row.cells)
    out, cols = [], sorted(row.expanded)
    i = 0
    while i < len(cols):  # merge runs of blank cells back into MULBLANK records
        col = cols[i]
        rt, body = row.expanded[col]
        if rt == BLANK:
            j = i
            while j + 1 < len(cols) and cols[j + 1] == cols[j] + 1 and row.expanded[cols[j + 1]][0] == BLANK:
                j += 1
            if j > i:
                r = struct.unpack_from("<H", body, 0)[0]
                xfs = b"".join(row.expanded[cols[k]][1][4:6] for k in range(i, j + 1))
                out.append(_pack(MULBLANK, struct.pack("<HH", r, col) + xfs + struct.pack("<H", cols[j])))
                i = j + 1
                continue
        out.append(_pack(rt, body))
        i += 1
    return b"".join(out)


def _parse_sheet(name: str, recs: list[tuple[int, bytes]]) -> _Sheet:
    first = next((k for k, (rt, _) in enumerate(recs) if rt in CELL_TABLE), None)
    if first is None:
        first = next(k for k, (rt, _) in enumerate(recs) if rt == 0x023E)  # WINDOW2
    last = first
    while last < len(recs) and recs[last][0] in CELL_TABLE:
        last += 1
    pre = [(rt, b) for rt, b in recs[:first] if rt != INDEX]
    post = recs[last:]
    if any(rt in CELL_TABLE and rt != DBCELL for rt, _ in post):
        raise TemplateError(f"unexpected cell records after the cell table in sheet {name!r}")

    col_xf: dict[int, int] = {}
    for rt, body in pre:
        if rt == 0x007D:  # COLINFO
            c1, c2, _w, xf = struct.unpack_from("<HHHH", body, 0)
            for c in range(c1, min(c2, 255) + 1):
                col_xf[c] = xf

    rows: dict[int, _Row] = {}
    current: _Row | None = None
    for rt, body in recs[first:last]:
        if rt == DBCELL:
            continue
        if rt == ROW:
            rows.setdefault(struct.unpack_from("<H", body, 0)[0], _Row()).record = body
            continue
        r = _cell_row(rt, body)
        if r is None:
            if current is None:
                raise TemplateError("orphan STRING record")
            current.cells.append((rt, body))
            continue
        current = rows.setdefault(r, _Row())
        current.cells.append((rt, body))
    return _Sheet(name, pre, rows, post, col_xf)


def _serialize_sheet(sh: _Sheet) -> bytes:
    rows = sorted(sh.rows)
    max_row = rows[-1] + 1 if rows else 0
    max_col = 0
    body = []
    for block_start in range(0, len(rows), 32):
        block = rows[block_start:block_start + 32]
        for r in block:
            row = sh.rows[r]
            if row.record is not None:
                rec = bytearray(row.record)
                if row.expanded:
                    lo, hi = min(row.expanded), max(row.expanded) + 1
                    c_mic, c_mac = struct.unpack_from("<HH", rec, 2)
                    struct.pack_into("<HH", rec, 2, min(c_mic, lo) if c_mac else lo, max(c_mac, hi))
                body.append(_pack(ROW, bytes(rec)))
                max_col = max(max_col, struct.unpack_from("<H", rec, 4)[0])
        for r in block:
            body.append(_serialize_row_cells(sh.rows[r]))
            if sh.rows[r].expanded:
                max_col = max(max_col, max(sh.rows[r].expanded) + 1)
    pre = []
    for rt, b in sh.pre:
        if rt == DIMENSIONS:
            rw_mic, rw_mac, c_mic, c_mac, res = struct.unpack("<IIHHH", b)
            b = struct.pack("<IIHHH", rw_mic, max(rw_mac, max_row), c_mic, max(c_mac, max_col), res)
        pre.append(_pack(rt, b))
    return b"".join(pre) + b"".join(body) + b"".join(_pack(rt, b) for rt, b in sh.post)


# ── Public API ────────────────────────────────────────────────

class XlsTemplate:
    """An .xls workbook whose cells can be overwritten in place."""

    def __init__(self, data: bytes):
        ole = olefile.OleFileIO(io.BytesIO(data))
        stream_name = "Workbook" if ole.exists("Workbook") else "Book"
        stream = ole.openstream(stream_name).read()
        self._extra_streams = {}
        recs = _records(stream)
        eof = next(k for k, (rt, _) in enumerate(recs) if rt == EOF)
        self._globals = recs[:eof + 1]

        sst_at = next((k for k, (rt, _) in enumerate(self._globals) if rt == SST), None)
        if sst_at is None:
            self._strings, self._sst_refs = [], 0
            self._sst_span = None
        else:
            end = sst_at + 1
            while self._globals[end][0] == CONTINUE:
                end += 1
            chunks = [b for _, b in self._globals[sst_at:end]]
            self._strings = _parse_sst(chunks)
            self._sst_refs = struct.unpack_from("<I", chunks[0], 0)[0]
            self._sst_span = (sst_at, end)
        self._index = {s: i for i, s in reversed(list(enumerate(self._strings)))}

        self._sheet_names: list[str] = []
        for rt, body in self._globals:
            if rt == BOUNDSHEET:
                cch, flag = body[6], body[7]
                raw = body[8:8 + cch * (2 if flag & 1 else 1)]
                self._sheet_names.append(raw.decode("utf-16-le" if flag & 1 else "latin-1"))

        self._sheets: list[_Sheet] = []
        pos = sum(4 + len(b) for _, b in self._globals)
        for name in self._sheet_names:
            sub = []
            for rt, body in _records(stream, pos):
                sub.append((rt, body))
                pos += 4 + len(body)
                if rt == EOF:
                    break
            self._sheets.append(_parse_sheet(name, sub))

    # -- reading ------------------------------------------------------
    @property
    def sheet_names(self) -> list[str]:
        return list(self._sheet_names)

    def sheet_index(self, name_or_index) -> int:
        if isinstance(name_or_index, int):
            return name_or_index
        lowered = [n.lower() for n in self._sheet_names]
        return lowered.index(str(name_or_index).lower())

    def row_count(self, sheet) -> int:
        rows = self._sheets[self.sheet_index(sheet)].rows
        return max(rows) + 1 if rows else 0

    def value(self, sheet, r: int, c: int):
        row = self._sheets[self.sheet_index(sheet)].rows.get(r)
        if row is None:
            return None
        cell = _expand(row).get(c)
        if cell is None:
            return None
        rt, body = cell
        if rt == LABELSST:
            return self._strings[struct.unpack_from("<I", body, 6)[0]]
        if rt == NUMBER:
            return struct.unpack_from("<d", body, 6)[0]
        if rt == RK:
            return _decode_rk(struct.unpack_from("<I", body, 6)[0])
        if rt == LABEL:
            cch, flag = struct.unpack_from("<HB", body, 6)
            raw = body[9:]
            return raw.decode("utf-16-le" if flag & 1 else "latin-1")
        return None

    # -- writing ------------------------------------------------------
    def _xf_for(self, sh: _Sheet, r: int, c: int, style_row: int | None) -> int:
        row = sh.rows.get(r)
        if row is not None:
            cell = _expand(row).get(c)
            if cell is not None:
                return struct.unpack_from("<H", cell[1], 4)[0]
        if style_row is not None and style_row in sh.rows:
            cell = _expand(sh.rows[style_row]).get(c)
            if cell is not None:
                return struct.unpack_from("<H", cell[1], 4)[0]
        return sh.col_xf.get(c, DEFAULT_XF)

    def _str_index(self, s: str) -> int:
        idx = self._index.get(s)
        if idx is None:
            idx = len(self._strings)
            self._strings.append(s)
            self._index[s] = idx
        self._sst_refs += 1
        return idx

    def set(self, sheet, r: int, c: int, value, style_row: int | None = None) -> None:
        """Write a value, keeping the cell's existing style.

        ``None``/``""`` clears the cell (the formatting stays). For a cell that
        has no style yet, the style of the same column in ``style_row`` is used.
        """
        sh = self._sheets[self.sheet_index(sheet)]
        xf = self._xf_for(sh, r, c, style_row)
        row = sh.row(r)
        if row.record is None and style_row is not None and sh.rows.get(style_row) and sh.rows[style_row].record:
            rec = bytearray(sh.rows[style_row].record)
            struct.pack_into("<H", rec, 0, r)
            row.record = bytes(rec)
        cells = _expand(row)
        if value is None or value == "":
            cells[c] = (BLANK, struct.pack("<HHH", r, c, xf))
        elif isinstance(value, bool):
            cells[c] = (NUMBER, struct.pack("<HHHd", r, c, xf, float(value)))
        elif isinstance(value, (int, float)):
            cells[c] = (NUMBER, struct.pack("<HHHd", r, c, xf, float(value)))
        else:
            cells[c] = (LABELSST, struct.pack("<HHHI", r, c, xf, self._str_index(str(value))))

    def clear_values(self, sheet, rows: range, cols: range | None = None) -> None:
        """Blank every non-empty cell in ``rows`` (optionally only ``cols``), keeping styles."""
        sh = self._sheets[self.sheet_index(sheet)]
        for r in rows:
            row = sh.rows.get(r)
            if row is None or not row.cells and not row.expanded:
                continue
            if all(rt in (BLANK, MULBLANK) for rt, _ in row.cells) and row.expanded is None:
                continue
            for c, (rt, body) in list(_expand(row).items()):
                if rt != BLANK and (cols is None or c in cols):
                    xf = struct.unpack_from("<H", body, 4)[0]
                    row.expanded[c] = (BLANK, struct.pack("<HHH", r, c, xf))

    def to_bytes(self) -> bytes:
        glob = []
        for k, (rt, body) in enumerate(self._globals):
            if self._sst_span and self._sst_span[0] <= k < self._sst_span[1]:
                if k == self._sst_span[0]:
                    sst = _build_sst(self._strings, max(self._sst_refs, len(self._strings)))
                    glob.append(_pack(SST, sst[0]))
                    glob.extend(_pack(CONTINUE, c) for c in sst[1:])
                continue
            if rt == EXTSST:
                continue
            glob.append((rt, body))
        sheets = [_serialize_sheet(sh) for sh in self._sheets]

        # Globals size is known once BOUNDSHEET offsets are filled (their size is fixed)
        def render(offsets: list[int]) -> bytes:
            out, n = [], 0
            for item in glob:
                if isinstance(item, bytes):
                    out.append(item)
                    continue
                rt, body = item
                if rt == BOUNDSHEET:
                    body = struct.pack("<I", offsets[n]) + body[4:]
                    n += 1
                out.append(_pack(rt, body))
            return b"".join(out)

        head = render([0] * len(sheets))
        offsets, pos = [], len(head)
        for s in sheets:
            offsets.append(pos)
            pos += len(s)
        stream = render(offsets) + b"".join(sheets)
        buf = io.BytesIO()
        XlsDoc().save(buf, stream)
        return buf.getvalue()


def _decode_rk(rk: int) -> float:
    if rk & 0x02:
        v = float(rk >> 2 if not rk & 0x80000000 else (rk >> 2) - (1 << 30))
    else:
        v = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    return v / 100 if rk & 0x01 else v
