"""Look and feel for the SitePower page: one stylesheet plus small HTML builders.

The visual language is a digital sketchpad: a light grey dot-grid canvas, flat white cards with big rounded
corners, pill buttons (highlighter yellow for the primary action, black for the rest), bold Poppins headlines
with an emoji sticker, and four accent colours (yellow, red, blue, peach). One soft shadow, on the nav bar.
Everything is plain CSS and HTML so it works natively and in the browser build (stlite). Any text that comes
from the user is escaped before it is placed in HTML.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence

YELLOW = "#e6e51e"
RED = "#f34646"
BLUE = "#466cf3"
PEACH = "#ff8562"
INK = "#000000"
WHITE = "#ffffff"
MIST = "#f2f2f2"
HAIRLINE = "#e6e6e6"

_CATEGORY_COLOURS = {
    "lifting": "#000000",
    "lighting": YELLOW,
    "welfare": BLUE,
    "tools": RED,
    "plant": "#9aa0b4",
    "drying": PEACH,
    "commissioning": "#9fb3fa",
    "Base load": "#e6e6e6",
}
_FALLBACK = ("#76716f", "#cccccc", "#7d95f7", "#f5a89d", "#c9c824", "#333333")


def category_colour(name: str) -> str:
    """A stable colour per equipment category; unknown categories get a deterministic fallback."""
    if name in _CATEGORY_COLOURS:
        return _CATEGORY_COLOURS[name]
    return _FALLBACK[sum(ord(c) for c in name) % len(_FALLBACK)]


CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=Poppins:wght@500;700&display=swap');
.stApp { background-color: #f2f2f2; background-image: radial-gradient(#d6d6d6 1.3px, transparent 1.3px); background-size: 24px 24px; color: #000;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding: 3.4rem 1.6rem 2rem; max-width: 100%; }
[data-testid="stVerticalBlock"] { gap: .6rem; }
[data-testid="stHorizontalBlock"] { gap: .8rem; }
p, li, label { line-height: 1.53; }
h1, h2, h3, h4 { font-family: Poppins, Inter, system-ui, sans-serif; font-weight: 700; color: #000; }

/* ---------- hero: a white card holding the headline and a browser-frame preview ---------- */
.sp-label { display: inline-block; background: #e6e51e; color: #000; border-radius: 3000px; padding: 6px 14px; font-size: 13px; font-weight: 500; }
.sp-hero { display: flex; flex-wrap: wrap; gap: 1.2rem; align-items: center; justify-content: space-between; background: #fff;
  border-radius: 30px; padding: 1.2rem 1.8rem; margin: 0 0 .8rem; }
.sp-hero-text { flex: 1 1 400px; min-width: 0; }
.sp-hero h1 { margin: .5rem 0 .1rem; padding: 0; font-size: 46px; line-height: 1.05; letter-spacing: -.074em; font-weight: 700; }
.sp-emo { display: inline-block; font-size: .85em; margin: 0 .04em; letter-spacing: 0; transform: translateY(-.03em) rotate(-8deg); }
.sp-lead { font-family: Poppins, Inter, sans-serif; font-size: 20px; line-height: 1.3; font-weight: 500; letter-spacing: -.02em; margin: 0 0 .3rem; }
.sp-hero p { margin: 0 0 .6rem; color: #333; font-size: 15px; max-width: 34rem; }
.sp-hero p.sp-lead { color: #000; }
.sp-chips { display: flex; flex-wrap: wrap; gap: .5rem; }
.sp-chips span { padding: 3px 11px; border-radius: 3000px; font-size: 12px; font-weight: 500; color: #000; }
.sp-chips span:nth-child(1) { background: #e6e51e; }
.sp-chips span:nth-child(2) { background: #ff8562; }
.sp-chips span:nth-child(3) { background: #466cf3; color: #fff; }
.sp-chips span:nth-child(4) { background: #f34646; color: #fff; }
.sp-preview { flex: 1 1 300px; max-width: 420px; min-width: 260px; background-color: #fff; background-image: radial-gradient(#e6e6e6 1.3px, transparent 1.3px);
  background-size: 20px 20px; border: 1px solid #e6e6e6; border-radius: 16px; padding: 1.4rem 1rem .5rem; position: relative; }
.sp-preview::before { content: ""; position: absolute; top: 10px; left: 12px; width: 9px; height: 9px; border-radius: 50%; background: #f34646;
  box-shadow: 15px 0 0 #e6e51e, 30px 0 0 #466cf3; }
.sp-preview svg { width: 100%; height: auto; display: block; }
.sp-hero-cap { font-size: 13px; color: #555; margin-top: .5rem; }

/* ---------- headings ---------- */
[data-testid="stHeading"] h2 { font-size: 26px; line-height: 1.1; letter-spacing: -.02em; padding: 0; margin-top: .4rem; }
[data-testid="stHeading"] h3 { font-size: 19px; letter-spacing: -.018em; padding: .2rem 0; }

/* ---------- KPI cards: tinted from the four accents, last one solid highlighter ---------- */
[data-testid="stMetric"] { background: #fff; border-radius: 24px; padding: .6rem 1rem; border: none; }
[data-testid="stMetricLabel"] p { color: #000; font-size: 14px; font-weight: 500; }
[data-testid="stMetricValue"] { font-size: 1.7rem; color: #000; font-family: Poppins, Inter, sans-serif; font-weight: 700; letter-spacing: -.03em; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]:nth-child(1) [data-testid="stMetric"] { background: #ffe0d6; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] { background: #dde4fd; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"] { background: #fcdcdc; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"] { background: #fff; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]:last-child [data-testid="stMetric"] { background: #e6e51e; }

/* ---------- cards, tables, alerts: flat white, big radii ---------- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 24px; overflow: hidden; background: #fff; border: 1px solid #e6e6e6; }
[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"] { background: #fff; border-radius: 24px; padding: .6rem; border: none; }
[data-testid="stExpander"], [data-testid="stExpander"] details { border-radius: 24px; background: #fff; border: none; box-shadow: none !important; }
[data-testid="stAlert"] { border-radius: 24px; border: none; background: #fff; color: #000; }
[data-testid="stAlert"] > div { background: transparent !important; color: #000 !important; }
[data-testid="stAlert"] svg { color: #466cf3; }

/* ---------- buttons: black pills, the primary one is highlighter yellow ---------- */
.stButton > button, .stDownloadButton > button { border-radius: 3000px; font-weight: 500; padding: .5rem 1.3rem; border: 1px solid #000;
  background: #000; color: #fff; transition: all .15s; box-shadow: none; }
.stButton > button:hover:not(:disabled), .stDownloadButton > button:hover { background: #333; color: #fff; border-color: #333; }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background: #e6e51e; color: #000; border-color: #e6e51e; }
.stButton > button[kind="primary"]:hover:not(:disabled) { background: #fff705; border-color: #fff705; color: #000; }
.stButton > button:disabled { opacity: .35; }

/* ---------- tabs: a floating white nav card, the only shadow on the page ---------- */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display: none; }
[data-testid="stTabs"] { overflow: visible !important; }
[role="tablist"] { position: sticky; top: .6rem; z-index: 900; gap: .2rem; background: #fff; padding: .3rem; border-radius: 30px; border: none;
  width: fit-content; max-width: 100%; box-shadow: rgba(0,0,0,.2) 0 10px 10px -5px; margin-bottom: 0; }
[data-testid="stTab"] { height: 2.3rem; padding: 0 1rem; border-radius: 3000px; background: transparent; display: flex; align-items: center;
  cursor: pointer; border-bottom: none !important; box-shadow: none !important; transition: background .15s; }
[data-testid="stTab"] p { font-size: 15px; font-weight: 500; color: #000; margin: 0; }
[data-testid="stTab"]:hover { background: #f2f2f2; }
[data-testid="stTab"][aria-selected="true"] { background: #e6e51e; }
[data-testid="stTab"][aria-selected="true"] p { font-weight: 700; }
[data-testid="stTab"]::after, [data-testid="stTab"]::before { display: none; }
[role="tablist"] > div:not([role="tab"]), [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none !important; }
[data-testid="stTabPanel"] { padding-top: .6rem; }

[data-testid="stExpander"] summary { background: #fff !important; border-radius: 24px; }
[data-testid="stExpander"] details[open] summary { border-radius: 24px 24px 0 0; }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { background: #fff; border-radius: 0 0 24px 24px; }
.vega-embed, .vega-embed canvas, .vega-embed svg { background: #fff !important; }
/* ---------- inputs ---------- */
input, textarea { border-radius: 16px !important; }
[data-testid="stFileUploaderDropzone"] { background: #fff; border: 2px dashed #ccc; border-radius: 24px; }
[data-testid="stSlider"] [role="slider"] { background: #000; }

/* ---------- the one notice: a red annotation tag that flashes and drops down ---------- */
.sp-notice { position: fixed; top: .8rem; right: 1.2rem; z-index: 1000; }
.sp-notice summary { list-style: none; cursor: pointer; display: inline-flex; align-items: center; gap: .5rem; padding: .5rem 1.1rem;
  border-radius: 3000px; background: #f34646; color: #fff; font-size: 13px; font-weight: 700; animation: sp-flash 1.3s ease-in-out infinite; }
.sp-notice summary::-webkit-details-marker { display: none; }
.sp-notice[open] summary { animation: none; background: #000; }
.sp-notice .sp-panel { margin-top: .5rem; width: min(380px, 88vw); background: #fff; border-radius: 30px; padding: 1.2rem 1.4rem; color: #000;
  font-size: 14px; line-height: 1.5; box-shadow: rgba(0,0,0,.2) 0 10px 10px -5px; }
.sp-notice .sp-panel p { margin: 0 0 .6rem; } .sp-notice .sp-panel p:last-child { margin: 0; }
@keyframes sp-flash { 0%, 100% { box-shadow: 0 0 0 0 rgba(243,70,70,.55); } 50% { box-shadow: 0 0 0 9px rgba(243,70,70,0); } }

/* ---------- guide cards ---------- */
.sp-guide { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin: .5rem 0; }
.sp-gcard { background: #fff; border-radius: 24px; padding: 1.2rem 1.4rem; }
.sp-gcard:nth-child(1) { background: #fff705; }
.sp-gcard:nth-child(2) { background: #fff; }
.sp-gcard:nth-child(3) { background: #ffe0d6; }
.sp-gcard:nth-child(4) { background: #dde4fd; }
.sp-gcard:nth-child(5) { background: #fff; }
.sp-gcard:nth-child(6) { background: #000; color: #fff; }
.sp-gcard:nth-child(6) h4, .sp-gcard:nth-child(6) p { color: #fff; }
.sp-gcard .sp-label { background: #000; color: #fff; }
.sp-gcard:nth-child(6) .sp-label { background: #e6e51e; color: #000; }
.sp-gcard h4 { margin: .5rem 0 .3rem; font-size: 20px; letter-spacing: -.018em; }
.sp-gcard p { margin: 0; font-size: 15px; color: #000; }

@media (max-width: 700px) { .sp-hero { padding: 1.5rem; } .sp-hero h1 { font-size: 42px; } }

</style>"""


def sparkline_svg(
    p10: Sequence[float],
    p50: Sequence[float],
    p90: Sequence[float],
    peak_index: int,
    width: int = 440,
    height: int = 130,
) -> str:
    """A small area chart of the weekly P10 to P90 band and median, drawn from zero so it cannot exaggerate."""
    n = len(p50)
    if n == 0 or len(p10) != n or len(p90) != n:
        raise ValueError("p10, p50 and p90 must be non-empty and the same length")
    pad = 10.0
    top = max(max(p90), 0.0)
    scale = top if top > 0 and math.isfinite(top) else 1.0

    def px(i: int) -> float:
        return pad + (width - 2 * pad) * (i / (n - 1) if n > 1 else 0.5)

    def py(v: float) -> float:
        return height - pad - (height - 2 * pad) * (max(v, 0.0) / scale)

    upper = [f"{px(i):.1f},{py(p90[i]):.1f}" for i in range(n)]
    lower = [f"{px(i):.1f},{py(p10[i]):.1f}" for i in reversed(range(n))]
    line = " ".join(f"{px(i):.1f},{py(p50[i]):.1f}" for i in range(n))
    pk = min(max(peak_index, 0), n - 1)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Weekly demand profile with its uncertainty band">'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#cccccc" />'
        f'<polygon points="{" ".join(upper + lower)}" fill="rgba(230,229,30,.55)" />'
        f'<polyline points="{line}" fill="none" stroke="#000000" stroke-width="3" stroke-linejoin="round" />'
        f'<circle cx="{px(pk):.1f}" cy="{py(p50[pk]):.1f}" r="6" fill="#f34646" stroke="#ffffff" stroke-width="3" />'
        "</svg>"
    )


def hero_html(project_name: str, weeks: int, spark: str, illustrative: bool) -> str:
    caption = f"{html.escape(project_name)} · {int(weeks)} weeks"
    if illustrative:
        caption += " · illustrative data"
    return (
        '<div class="sp-hero">'
        '<div class="sp-hero-text">'
        '<div class="sp-label">Temporary site power</div>'
        '<h1>Site<span class="sp-emo">&#9889;</span>Power</h1>'
        '<p class="sp-lead">Size a site&rsquo;s temporary power week by week, and see how uncertain it is.</p>'
        '<div class="sp-chips"><span>Seeded Monte Carlo</span><span>Traceable to every line</span>'
        "<span>Calibrates on held-out weeks</span><span>Runs in your browser</span></div>"
        "</div>"
        f'<div class="sp-preview">{spark}<div class="sp-hero-cap">{caption}</div></div>'
        "</div>"
    )


def notice_html(illustrative: bool) -> str:
    """The single warning: a flashing badge that drops a panel down on click. Static text only."""
    body = (
        "<p><b>Planning estimate only.</b> Results depend on the equipment figures, load factors and diversity "
        "assumptions entered. This is not a supply design or a quotation. Confirm with the supplier and a "
        "competent person.</p>"
    )
    if illustrative:
        body += (
            "<p><b>The equipment figures are illustrative placeholders, not real data.</b> Load your own "
            "equipment CSV (Project tab, then &ldquo;Load your own data&rdquo;) before relying on any number.</p>"
        )
    return (
        '<details class="sp-notice"><summary>&#9888; Read before use</summary>'
        f'<div class="sp-panel">{body}</div></details>'
    )


_GUIDE = (
    (
        "STEP 1",
        "Project",
        "Name the job and set how many weeks it runs. In the equipment schedule, add a row for "
        "each item of kit: which equipment, how many, and the first and last week it is on site. Add a base load for "
        "things that are always on (cabins, security lighting).",
    ),
    (
        "STEP 2",
        "Overview",
        "See the demand in kW and kVA for every week, with a band showing P10 to P90 across "
        "the trials. The <b>Recommended supply</b> card is the smallest standard size above the P90 peak plus your "
        "headroom. The Detail tab shows which equipment made up any week.",
    ),
    (
        "STEP 3",
        "Compare and cost",
        "Edit a copy of the schedule to compare two options side by side, and test a "
        "generator against a grid connection using your own prices.",
    ),
    (
        "STEP 4",
        "Calibrate (optional)",
        "If you have meter readings from a similar site, upload them. SitePower "
        "proposes a scale for your load factors and judges it only on weeks it was not fitted on. Nothing changes "
        "until you press Apply, and you can remove it again.",
    ),
    (
        "STEP 5",
        "Export &amp; notes",
        "Download the weekly profile as CSV, the project as JSON, or a printable HTML "
        "report, and read how the numbers are calculated.",
    ),
    (
        "TERMS",
        "Reading the numbers",
        "<b>kW</b> is real power; <b>kVA</b> is what the supply must carry (kW / "
        "power factor). <b>Load factor</b> is the share of rated power an item really draws. <b>Diversity</b> allows "
        "for items not all running at once. <b>P90</b> means 90% of trials came in at or below that value.",
    ),
)


def guide_html() -> str:
    """Step cards for the How to use tab. Static text only."""
    cards = "".join(
        f'<div class="sp-gcard"><span class="sp-label">{tag}</span><h4>{title}</h4><p>{text}</p></div>'
        for tag, title, text in _GUIDE
    )
    intro = (
        "<p>SitePower estimates how much electrical power a construction site needs <b>each week</b>, from "
        "the equipment you plan to hire, and shows how uncertain that estimate is. Work through the tabs in "
        "order. The sample project is already loaded, so the Overview tab already shows a result.</p>"
    )
    return f'{intro}<div class="sp-guide">{cards}</div>'


GUIDE_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "Quick start: your first estimate in 60 seconds",
        """
1. Open the **Overview** tab. The sample project (a 6-storey block, 24 weeks) is already loaded, so you already have a result.
2. Read the five cards: **central peak**, **median peak**, **90% below** peak, **P90 kVA**, and the **Recommended supply**.
3. Move the **Headroom** slider to add a safety margin, or the **Schedule slip** slider to allow for late hires, and watch the cards and charts react.
4. Go to **Project** and change the schedule (add a crane, move a hire by two weeks) to see how the answer moves.
5. Download a **PDF report** from **Export & notes** to keep or send.
""",
    ),
    (
        "Tab by tab: what every control does",
        """
**Overview**
- *Headroom above the P90 peak*: extra capacity on top of the P90 peak kVA, as a percentage. The recommended supply is the smallest listed size at or above `P90 peak kVA x (1 + headroom)`.
- *Schedule slip (weeks)*: every hire may start up to this many whole weeks late, drawn at random in each trial. 0 means the schedule is exact.
- *Show demand in*: switches the left chart between kW (real power) and kVA (what the supply must carry).
- *Cards*: central = every item at its most likely load factor; median and 90%-below come from the random trials; P90 kVA is the figure used for sizing.
- *Weekly demand chart*: yellow band = P10 to P90 of the trials, black line = median, red dashed = central estimate, dot = the week the peak most often falls in.
- *Where the demand comes from*: the central estimate split by equipment category, so the layers add up to the red dashed line.

**Project**
- *Load your own data*: upload an equipment library (CSV) or a saved project (JSON), or reset to the sample.
- *Project name, Weeks, Base load, Base power factor*: the base load is power that is always on (cabins, security lighting, site office).
- *Group diversity factors*: items in the same group rarely all run at full load together. A factor of 0.8 means the group is counted at 80%. These are your assumptions.
- *Equipment schedule*: one row per hire: which equipment, how many, first week, last week (weeks start at 1). Add rows with the empty last row, delete with the row menu. Bad rows are reported and ignored, the rest still count.

**Detail**
- *Monte Carlo trials and seed*: more trials give a smoother estimate; the same seed always gives the same answer.
- *Why is a week the size it is?*: pick any week to see every equipment line that contributes, before diversity.
- *What drives that week?*: bar chart of the biggest contributors, with a note on how many types make up about 80% of the demand.
- *Phases*: group weeks (for example groundworks, frame, fit-out) to see each phase's own peak and P90 kVA.

**Compare**
- Scenario A is your Project tab schedule. Scenario B starts as a copy; edit it (for example swap a tower crane for a mobile crane) to see the change in peak, supply size and energy, with the two profiles overlaid.

**Cost**
- A deliberately simple comparison of a grid connection against a generator, using *your* prices: working hours per week, one-off connection cost, grid price per kWh, generator hire per week and fuel cost per kWh. It shows the totals, the cumulative cost curves and the week where the generator overtakes the grid, if it does.

**Calibrate**
- Compare the estimate against real meter readings from a similar site and let SitePower propose a correction. Details below.

**Export & notes**
- Weekly profile (CSV), project (JSON), and a report as PDF or printable HTML. The notes explain the calculation and its limits.
""",
    ),
    (
        "Worked example with the sample project",
        """
In the sample project the peak falls in **week 21**. Using the illustrative figures:

- Central estimate in week 21: **136 kW** (every item at its most likely load factor, after diversity, plus the 3 kW base load).
- Over 2000 random trials the median peak is about **142 kW** and 90% of trials stay below about **156 kW**.
- kVA divides each item's kW by its power factor, so the P90 peak is about **169 kVA**.
- With 15% headroom the requirement is `169 x 1.15 = 195 kVA`, so the smallest listed size at or above it is **200 kVA**.

Try it: at 0% headroom the requirement is 169 kVA and the recommendation stays 200 kVA (the next size up). At 50% it becomes 253 kVA, which selects the 315 kVA size. Then set schedule slip to 4 weeks and watch the P90 peak and the band change.
""",
    ),
    (
        "Using your own data",
        """
**Equipment library (CSV)**: one row per item. Required columns:

```
id,name,category,rated_kw,power_factor,load_factor_min,load_factor_mode,load_factor_max,diversity_group,source
crane1,Tower crane,lifting,45,0.85,0.25,0.40,0.65,cranes,hire sheet 2025-03
```

- `rated_kw` is the nameplate power. `power_factor` is between 0 and 1.
- The three load factors are the share of rated power the item really draws: `0 < min <= mode <= max <= 1`.
- `diversity_group` is optional; items sharing a group are summed and then multiplied by that group's factor.
- Rows with problems are reported with their row number; the other rows still load.

**Project (JSON)**: use *Project (JSON)* on the Export tab to save your work, and upload it later from *Load your own data*.

**Metered data (CSV)** for calibration: two columns, `timestamp,kw` (ISO timestamps, any interval). Lines starting with `#` are comments.
""",
    ),
    (
        "How the result is built",
        """
1. **Each booking** contributes `quantity x rated kW x load factor` in every week it is on site.
2. **Diversity**: items in a group are added up and multiplied by the group's factor. A base load is added every week.
3. **kVA**: each item's kW is divided by its power factor and the results are added (a conservative simplification that ignores phase angles).
4. **Uncertainty**: in each trial, every equipment type draws one load factor from a triangular distribution (min, most likely, max). All hires of one type share the draw, which is conservative for the peak.
5. **Slip** (optional): each hire may start up to N weeks late; anything pushed past the last week is dropped.
6. **Percentiles**: P10, P50 and P90 are taken across the trials for every week, and the peak of every trial gives the peak percentiles.
7. **Sizing**: `P90 peak kVA x (1 + headroom)`, then the smallest size on the (illustrative) list.
""",
    ),
    (
        "Calibrating against meter readings, step by step",
        """
1. Open the **Calibrate** tab. Upload meter readings (`timestamp,kw`), or tick *Use the SYNTHETIC sample instead* to try it.
2. Set the date of **week 1** so readings line up with your project weeks.
3. Choose *One scale for all equipment* (recommended) or *One scale per category* (advanced; needs many weeks of data and warns when there are too few).
4. SitePower fits on the **first 70%** of the weeks that have data and reports errors on the **remaining held-out weeks** only, so the improvement is honest.
5. If the held-out error does not improve, it warns you and disables **Apply**. If it does, press **Apply these scales to the estimate**. A banner then appears on the Overview tab and your own figures are never overwritten.
6. Use **Remove the calibration** to return to your original numbers exactly.

The bundled meter file is **synthetic**: it shows how the mechanics work and says nothing about accuracy on a real site.
""",
    ),
    (
        "Glossary",
        """
- **kW / kVA**: real power / apparent power. kVA = kW divided by power factor; supplies are sized in kVA.
- **Load factor**: the share of an item's rated power it really draws while on site.
- **Diversity factor**: allowance for items not all running at full load together.
- **P10 / P50 / P90**: the value that 10% / 50% / 90% of trials fall below. P90 is a cautious planning figure.
- **Central estimate**: the single deterministic answer with every item at its most likely load factor.
- **Headroom**: a safety margin added on top of the P90 peak before choosing a size.
- **Monte Carlo**: many random what-if runs; the spread of the results shows the uncertainty.
- **Seed**: the starting number of the random draws. Same seed, same result.
- **Held-out weeks**: weeks kept back from fitting, used only to judge whether a calibration really helps.
- **Schedule slip**: hires starting later than planned.
""",
    ),
    (
        "Troubleshooting and FAQ",
        """
- **The first load is slow.** The page downloads Python and its libraries to run in your browser (about 40 MB the first time). Later visits are much faster.
- **A schedule row is ignored.** Read the red message under the table: unknown equipment, a week outside the project, or an end week before the start week.
- **The Apply button is greyed out.** The proposed calibration did not improve error on the held-out weeks, so it is not offered.
- **The numbers changed when I reloaded.** They should not: with the same seed, trials, data and settings the result is identical. Check the seed on the Detail tab.
- **Why is the recommended supply bigger than the peak?** Headroom is added, then the next listed size up is chosen.
- **Where does my data go?** Nowhere. Everything runs in your browser and nothing is uploaded.
""",
    ),
    (
        "Limits you should know about",
        """
- The bundled equipment figures and supply sizes are **illustrative placeholders**. Load your own before relying on any number.
- The uncertainty band covers load-factor uncertainty, plus schedule slip if you set it. It does **not** cover missing equipment, wrong diversity factors or wrong rated powers.
- The cost model is simple (connection, energy and weekly hire only) and every price is yours to enter.
- This is a planning estimate, not a supply design, a network study or a quotation. Confirm with the supplier and a competent person.
""",
    ),
)
