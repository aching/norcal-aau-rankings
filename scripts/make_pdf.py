#!/usr/bin/env python3
"""Minimal stdlib-only markdown -> PDF (raw PDF 1.4, Helvetica core font).

Usage: python3 make_pdf.py TITLE INPUT.md OUTPUT.pdf

Supported markdown subset:
  # H1, ## H2, plain paragraphs, `- ` bullets, `| tables |`
  (bold markers ** are stripped; cells truncate to column width).
Layout: US Letter, footer page numbers, repeated table headers.
"""
import re
import sys


def esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def clean(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    return s.replace("\u2014", "--").replace("\u2013", "-").replace(
        "\u2192", "->").replace("\u2605", "*").replace(
        "\U0001F3C6", "[T]").encode("latin-1", "replace").decode("latin-1")


class PDF:
    def __init__(self):
        self.objs = []
        self.page_ids = []

    def add(self, body):
        self.objs.append(body)
        return len(self.objs)

    def build(self):
        out = ["%PDF-1.4"]
        offs = []
        for i, b in enumerate(self.objs):
            offs.append(sum(len(x) + 1 for x in out))
            out.append(f"{i + 1} 0 obj\n{b}\nendobj")
        xref = sum(len(x) + 1 for x in out)
        out.append(f"xref\n0 {len(self.objs) + 1}\n"
                   "0000000000 65535 f ")
        for o in offs:
            out.append(f"{o:010d} 00000 n ")
        out.append(f"trailer\n<< /Size {len(self.objs) + 1} "
                   f"/Root 1 0 R >>\nstartxref\n{xref}\n%%EOF")
        return "\n".join(out)


PW, PH = 612, 792
ML, MR, MT, MB = 48, 48, 56, 56


class Doc:
    def __init__(self, pdf, font_id):
        self.pdf = pdf
        self.font = font_id
        self.ops = []
        self.y = PH - MT
        self.n = 0

    def new_page(self):
        if self.ops:
            self.flush()
        self.n += 1
        self.y = PH - MT
        self.ops = []

    def flush(self):
        if not self.ops:
            return
        ops = list(self.ops)
        # footer
        ops.append(f"BT /F1 8 Tf 1 0 0 1 {PW/2-20:.0f} 30 Tm "
                   f"({self.n}) Tj ET")
        cid = self.pdf.add("<< /Length %d >>\nstream\n%s\nendstream" % (
            len(" ".join(ops)), " ".join(ops)))
        pid = self.pdf.add(f"<< /Type /Page /Parent 2 0 R "
                           f"/MediaBox [0 0 {PW} {PH}] "
                           f"/Resources << /Font << /F1 {self.font} 0 R >> >> "
                           f"/Contents {cid} 0 R >>")
        self.pdf.page_ids.append(pid)
        self.ops = []

    def need(self, h):
        if self.y - h < MB:
            self.new_page()

    def text(self, x, size, s, bold=False):
        self.need(size + 4)
        self.ops.append(f"BT /F1 {size} Tf 1 0 0 1 {x:.0f} "
                        f"{self.y:.0f} Tm ({esc(s)}) Tj ET")
        self.y -= size + 4

    def rule(self):
        self.need(10)
        self.ops.append(f"0.7 g 0.5 w {ML} {self.y:.0f} m "
                        f"{PW-MR} {self.y:.0f} l S 0 g")
        self.y -= 10

    def shade(self, h):
        self.ops.append(f"0.94 g {ML} {self.y-h:.0f} {PW-ML-MR} {h:.0f} re f 0 g")


def col_widths(rows, avail, maxw=150, minw=34):
    nc = len(rows[0])
    mx = [0] * nc
    for r in rows:
        for i, c in enumerate(r):
            mx[i] = max(mx[i], len(c))
    tot = sum(mx) or 1
    ws = [max(minw, min(maxw, m / tot * avail)) for m in mx]
    # scale to fit
    s = avail / sum(ws)
    return [w * s for w in ws]


def wrap(text, width_chars):
    """Greedy word-wrap; long words hard-break. Returns list of lines."""
    if width_chars < 5:
        width_chars = 5
    words, lines, cur = text.split(), [], ""
    for w in words:
        while len(w) > width_chars:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(w[:width_chars])
            w = w[width_chars:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_table(doc, rows):
    if not rows:
        return
    avail = PW - ML - MR
    ws = col_widths(rows, avail)
    xs = [ML]
    for w in ws:
        xs.append(xs[-1] + w)
    FS = 7.5
    LH = 10  # line height for wrapped rows

    def cell_lines(c, i):
        return wrap(c, max(5, int(ws[i] / (FS * 0.55))))

    def header():
        doc.need(LH)
        top = doc.y
        doc.shade(LH)
        for i, c in enumerate(rows[0]):
            doc.ops.append(
                f"BT /F1 {FS} Tf 1 0 0 1 {xs[i]+3:.0f} {top-9:.0f} "
                f"Tm ({esc(' '.join(cell_lines(c, i))[:120])}) Tj ET")
        doc.y -= LH

    header()
    for r in rows[1:]:
        wrapped = [cell_lines(c, i) for i, c in enumerate(r)]
        nlines = max(len(w) for w in wrapped)
        rh = nlines * LH
        if doc.y - rh < MB:
            doc.new_page()
            header()
        top = doc.y
        for li in range(nlines):
            for i, w in enumerate(wrapped):
                s = w[li] if li < len(w) else ""
                if s:
                    doc.ops.append(
                        f"BT /F1 {FS} Tf 1 0 0 1 {xs[i]+3:.0f} "
                        f"{top - li*LH - 9:.0f} "
                        f"Tm ({esc(s)}) Tj ET")
        doc.y -= rh


def parse(md):
    blocks = []
    tbl = []
    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if re.match(r"^[\s:\-|]+$", line.replace("|", "")):
                continue
            tbl.append(cells)
        else:
            if tbl:
                blocks.append(("table", tbl))
                tbl = []
            if line.startswith("## "):
                blocks.append(("h2", line[3:]))
            elif line.startswith("# "):
                blocks.append(("h1", line[2:]))
            elif line.startswith("- "):
                blocks.append(("li", line[2:]))
            elif line.strip() == "":
                blocks.append(("sp", ""))
            else:
                blocks.append(("p", line))
    if tbl:
        blocks.append(("table", tbl))
    return blocks


def main():
    title, inp, outp = sys.argv[1], sys.argv[2], sys.argv[3]
    md = open(inp).read()
    from datetime import date
    today = date.today().isoformat()
    pdf = PDF()
    pdf.add("<< /Type /Catalog /Pages 2 0 R >>")  # id 1: catalog (Root)
    pdf.add("<< /Type /Pages /Kids [] /Count 0 >>")  # id 2: pages (fixed later)
    font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    doc = Doc(pdf, font)
    doc.new_page()
    doc.text(ML, 22, clean(title))
    doc.text(ML, 10, f"NorCal AAU rankings  |  generated {today}")
    doc.text(ML, 8, "Score = per-game credit (tier x decay x margin x title) x opponent strength, iterated 15x. "
             "Tier: nat 1.0 / up .85 / gold .75 / open .5 / silver .5 / bronze .25. "
             "Margin: log curve capped at 25 (squeaker ~0.85x, median ~1.0x, 20pts ~1.15x). "
             "Ghosts (<9g) give no opp strength; only prelim top-10 confer credit; scores shrink by n/(n+8). "
             "Title x1.5 champ wins (prestige Made Hoops/G365/OGP stacks x1.25).")
    doc.rule()
    for kind, val in parse(md):
        v = clean(val) if isinstance(val, str) else val
        if kind == "h1":
            doc.text(ML, 16, v)
        elif kind == "h2":
            doc.y -= 4
            doc.text(ML, 12, v)
        elif kind == "p":
            doc.text(ML, 9, v)
        elif kind == "li":
            doc.text(ML + 12, 9, "- " + v)
        elif kind == "sp":
            doc.y -= 6
        elif kind == "table":
            draw_table(doc, [[clean(c) for c in r] for r in val])
            doc.y -= 6
    doc.flush()
    # fix Pages object (id 2) with real kids
    kids = " ".join(f"{p} 0 R" for p in pdf.page_ids)
    pdf.objs[1] = (f"<< /Type /Pages /Kids [{kids}] "
                   f"/Count {len(pdf.page_ids)} >>")
    data = pdf.build()
    open(outp, "w").write(data)
    print(f"wrote {outp} ({len(data)} bytes, "
          f"{len(pdf.page_ids)} pages)")


main()
