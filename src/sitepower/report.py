"""A standalone, printable HTML report of an estimate (no scripts, no external files). User text is escaped."""

from __future__ import annotations

import html
from collections.abc import Sequence

from sitepower.models import Estimate
from sitepower.montecarlo import MonteCarloResult
from sitepower.uimodel import Headline

DISCLAIMER = (
    "Planning estimate only. Results depend on the equipment figures, load factors and diversity "
    "assumptions entered. This is not a supply design or a quotation. Confirm with the supplier and "
    "a competent person."
)


def _chart(det: Estimate, mc: MonteCarloResult, w: int = 720, h: int = 220) -> str:
    n = len(det.kw)
    top = float(max(mc.p90_kw.max(), det.kw.max(), 1.0))
    pad = 28.0

    def x(i: int) -> float:
        return pad + (w - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)

    def y(v: float) -> float:
        return h - pad - (h - 2 * pad) * v / top

    band = [f"{x(i):.1f},{y(mc.p90_kw[i]):.1f}" for i in range(n)] + [
        f"{x(i):.1f},{y(mc.p10_kw[i]):.1f}" for i in reversed(range(n))
    ]
    line = " ".join(f"{x(i):.1f},{y(mc.p50_kw[i]):.1f}" for i in range(n))
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Weekly demand with P10 to P90 band">'
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#999"/>'
        f'<polygon points="{" ".join(band)}" fill="#e6e51e" opacity=".6"/>'
        f'<polyline points="{line}" fill="none" stroke="#000000" stroke-width="2.5"/>'
        f'<text x="{pad}" y="{pad - 10}" font-size="11" fill="#555">kW, peach band = P10 to P90, line = median</text>'
        f'<text x="{w - pad}" y="{h - 8}" font-size="11" fill="#555" text-anchor="end">week {n}</text>'
        "</svg>"
    )


def report_html(
    project_name: str,
    det: Estimate,
    mc: MonteCarloResult,
    head: Headline,
    assumptions: Sequence[str],
    illustrative: bool,
) -> str:
    esc = html.escape
    rows = "".join(
        f"<tr><td>{i + 1}</td><td>{det.kw[i]:.1f}</td><td>{mc.p10_kw[i]:.1f}</td>"
        f"<td>{mc.p50_kw[i]:.1f}</td><td>{mc.p90_kw[i]:.1f}</td><td>{mc.p90_kva[i]:.1f}</td></tr>"
        for i in range(len(det.kw))
    )
    size = (
        f"{head.sizing.recommended_kva:.0f} kVA"
        if head.sizing.recommended_kva
        else "above the listed sizes"
    )
    warn = (
        '<p class="warn"><b>The equipment figures are illustrative placeholders, not real data.</b></p>'
        if illustrative
        else ""
    )
    items = "".join(f"<li>{esc(a)}</li>" for a in assumptions)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>SitePower report: {esc(project_name)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#0e0e0f;background:#f2f2f2}}
h1{{font-weight:500;letter-spacing:-.03em}} h1 span{{color:#000000}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin:1rem 0}}
.k div{{background:#fff;border:1px solid #e6e6e6;border-radius:18px;padding:.8rem 1rem}}
.k b{{display:block;font-size:1.5rem;font-weight:500}} .k div:last-child{{background:#e6e51e}}
table{{border-collapse:collapse;width:100%;font-size:.85rem;background:#fff}}
td,th{{border:1px solid #e6e6e6;padding:.3rem .5rem;text-align:right}} th{{background:#e6e6e6}}
.warn{{background:#fcdcdc;border-radius:14px;padding:.6rem 1rem}} .note{{color:#555;font-size:.85rem}}
@media print{{body{{background:#fff}}}}
</style></head><body>
<h1>Site<span>Power</span> report</h1>
<p><b>{esc(project_name)}</b> &middot; {len(det.kw)} weeks &middot; {mc.trials} trials, seed {mc.seed}</p>
{warn}
<div class="k">
<div>Peak, central<b>{head.deterministic_peak_kw:.0f} kW</b></div>
<div>Peak, median<b>{head.p50_peak_kw:.0f} kW</b></div>
<div>Peak, 90% below<b>{head.p90_peak_kw:.0f} kW</b></div>
<div>Peak kVA (P90)<b>{head.p90_peak_kva:.0f} kVA</b></div>
<div>Recommended supply<b>{size}</b></div>
</div>
<p class="note">Most likely peak week: {head.most_likely_peak_week}. {esc(head.sizing.note)}</p>
{_chart(det, mc)}
<h2>Weekly profile</h2>
<table><tr><th>Week</th><th>Central kW</th><th>P10 kW</th><th>P50 kW</th><th>P90 kW</th><th>P90 kVA</th></tr>{rows}</table>
<h2>Assumptions</h2><ul>{items}</ul>
<p class="note">{esc(DISCLAIMER)} The band reflects load-factor uncertainty (and schedule slip, if set) only.</p>
</body></html>"""
