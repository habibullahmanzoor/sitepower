"""A small, dependency-free PDF report writer (one or two A4 pages, built-in Helvetica, vector chart).

It writes the PDF syntax directly so it runs unchanged natively and in the browser build (no reportlab).
Text is limited to Latin-1; anything else is replaced with '?'. User text is only ever drawn as text.
"""

from __future__ import annotations

from collections.abc import Sequence

from sitepower.models import Estimate
from sitepower.montecarlo import MonteCarloResult
from sitepower.report import DISCLAIMER
from sitepower.uimodel import Headline

W, H = 595.0, 842.0  # A4 in points
MARGIN = 40.0


def _esc(s: str) -> str:
    b = s.encode("latin-1", "replace").decode("latin-1")
    return b.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"0 0 0 rg BT /{font} {size:.1f} Tf {x:.1f} {y:.1f} Td ({_esc(s)}) Tj ET")

    def rect(self, x: float, y: float, w: float, h: float, rgb: tuple[float, float, float]) -> None:
        self.ops.append(
            f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f"
        )

    def line(
        self,
        pts: Sequence[tuple[float, float]],
        rgb: tuple[float, float, float],
        width: float = 1.0,
    ) -> None:
        if len(pts) < 2:
            return
        path = f"{pts[0][0]:.1f} {pts[0][1]:.1f} m " + " ".join(
            f"{x:.1f} {y:.1f} l" for x, y in pts[1:]
        )
        self.ops.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} RG {width:.1f} w {path} S")

    def polygon(self, pts: Sequence[tuple[float, float]], rgb: tuple[float, float, float]) -> None:
        path = f"{pts[0][0]:.1f} {pts[0][1]:.1f} m " + " ".join(
            f"{x:.1f} {y:.1f} l" for x, y in pts[1:]
        )
        self.ops.append(f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg {path} h f")

    def stream(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")


def _wrap(s: str, width_chars: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def report_pdf(
    project_name: str,
    det: Estimate,
    mc: MonteCarloResult,
    head: Headline,
    assumptions: Sequence[str],
    illustrative: bool,
) -> bytes:
    """Return a PDF: headline numbers, the weekly chart with its P10 to P90 band, assumptions, weekly table."""
    black, yellow, red, grey = (
        (0.0, 0.0, 0.0),
        (0.90, 0.90, 0.12),
        (0.95, 0.27, 0.27),
        (0.45, 0.45, 0.45),
    )
    n = len(det.kw)
    pages: list[_Page] = []
    p = _Page()
    pages.append(p)
    y = H - MARGIN
    p.rect(0, H - 8, W, 8, yellow)
    p.text(MARGIN, y - 18, "SitePower report", 22, True)
    y -= 40
    p.text(MARGIN, y, f"{project_name}  |  {n} weeks  |  {mc.trials} trials, seed {mc.seed}", 10)
    y -= 22
    if illustrative:
        p.rect(MARGIN, y - 6, W - 2 * MARGIN, 20, (0.99, 0.86, 0.86))
        p.text(
            MARGIN + 8,
            y,
            "The equipment figures are illustrative placeholders, not real data.",
            9.5,
            True,
        )
        y -= 26
    size = (
        f"{head.sizing.recommended_kva:.0f} kVA"
        if head.sizing.recommended_kva
        else "above listed sizes"
    )
    cards = [
        ("Peak, central", f"{head.deterministic_peak_kw:.0f} kW"),
        ("Peak, median", f"{head.p50_peak_kw:.0f} kW"),
        ("Peak, 90% below", f"{head.p90_peak_kw:.0f} kW"),
        ("Peak kVA (P90)", f"{head.p90_peak_kva:.0f} kVA"),
        ("Recommended supply", size),
    ]
    cw = (W - 2 * MARGIN - 4 * 8) / 5
    for i, (label, value) in enumerate(cards):
        x = MARGIN + i * (cw + 8)
        p.rect(x, y - 44, cw, 50, yellow if i == 4 else (0.93, 0.93, 0.93))
        p.text(x + 6, y - 6, label, 7.5)
        p.text(x + 6, y - 30, value, 13, True)
    y -= 62
    for line in _wrap(
        f"Most likely peak week: {head.most_likely_peak_week}. {head.sizing.note}", 105
    ):
        p.text(MARGIN, y, line, 8.5)
        y -= 11
    y -= 8

    # chart
    cx0, cx1 = MARGIN + 28, W - MARGIN
    ch, cy1 = 170.0, y
    cy0 = cy1 - ch
    top = float(max(mc.p90_kw.max(), det.kw.max(), 1.0))

    def px(i: int) -> float:
        return cx0 + (cx1 - cx0) * (i / (n - 1) if n > 1 else 0.5)

    def py(v: float) -> float:
        return cy0 + ch * v / top

    p.line([(cx0, cy0), (cx1, cy0)], grey, 0.8)
    p.line([(cx0, cy0), (cx0, cy1)], grey, 0.8)
    p.text(MARGIN, cy1 - 6, f"{top:.0f}", 7)
    p.text(MARGIN, cy0 - 2, "0", 7)
    p.polygon(
        [(px(i), py(float(mc.p90_kw[i]))) for i in range(n)]
        + [(px(i), py(float(mc.p10_kw[i]))) for i in reversed(range(n))],
        (0.96, 0.96, 0.62),
    )
    p.line([(px(i), py(float(det.kw[i]))) for i in range(n)], red, 1.0)
    p.line([(px(i), py(float(mc.p50_kw[i]))) for i in range(n)], black, 1.8)
    step = max(1, n // 12)
    for i in range(0, n, step):
        p.text(px(i) - 3, cy0 - 12, str(i + 1), 7)
    p.text(cx1 - 20, cy0 - 22, "week", 7)
    p.text(
        cx0 + 4, cy1 - 12, "yellow = P10 to P90, black = median, red = central estimate (kW)", 7.5
    )
    y = cy0 - 40

    p.text(MARGIN, y, "Assumptions", 12, True)
    y -= 15
    for a in assumptions:
        for k, line in enumerate(_wrap(a, 105)):
            p.text(MARGIN + (8 if k else 0), y, ("- " if k == 0 else "") + line, 8.5)
            y -= 11
    y -= 6
    for line in _wrap(
        DISCLAIMER + " The band reflects load-factor uncertainty (and schedule slip, if set) only.",
        110,
    ):
        p.text(MARGIN, y, line, 8)
        y -= 10
    y -= 12

    # weekly table, continuing on extra pages as needed
    def header(pg: _Page, yy: float) -> float:
        pg.text(MARGIN, yy, "Weekly profile (kW; P90 also in kVA)", 12, True)
        yy -= 16
        cols = ("Week", "Central", "P10", "P50", "P90", "P90 kVA")
        for j, c in enumerate(cols):
            pg.text(MARGIN + j * 70, yy, c, 8.5, True)
        return yy - 12

    y = header(p, y)
    for i in range(n):
        if y < MARGIN + 20:
            p = _Page()
            pages.append(p)
            y = header(p, H - MARGIN)
        vals = (
            str(i + 1), f"{det.kw[i]:.1f}", f"{mc.p10_kw[i]:.1f}", f"{mc.p50_kw[i]:.1f}",
            f"{mc.p90_kw[i]:.1f}", f"{mc.p90_kva[i]:.1f}",
        )  # fmt: skip
        for j, v in enumerate(vals):
            p.text(MARGIN + j * 70, y, v, 8.5)
        y -= 11
    return _assemble(pages)


def _assemble(pages: Sequence[_Page]) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(pages)))
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())  # 2
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")  # 3
    add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )  # 4
    for i, pg in enumerate(pages):
        content_id = 6 + 2 * i
        add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.0f} {H:.0f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )  # 5 + 2i
        data = pg.stream()
        add(
            b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"
        )  # 6 + 2i
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
