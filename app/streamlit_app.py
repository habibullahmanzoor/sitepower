"""SitePower web page: a thin layer over the tested `sitepower` library. No calculations live here."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Lets `streamlit run app/streamlit_app.py` work from a plain checkout, with no `pip install -e .` first
# (which is how free hosts run it). When the package is installed this changes nothing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from sitepower.analysis import compare_costs, energy_kwh, peak_drivers, phase_summary
from sitepower.calibrate import (
    CalibrationError,
    apply_scales,
    calibrate,
    category_matrix,
    parse_metered_csv,
    weekly_peaks,
)
from sitepower.estimate import estimate
from sitepower.io import ProjectError, profile_to_csv, project_from_json, project_to_json
from sitepower.library import find_library_path, is_illustrative, parse_equipment_csv
from sitepower.models import Project
from sitepower.montecarlo import simulate
from sitepower.pdf import report_pdf
from sitepower.report import report_html
from sitepower.uimodel import bookings_to_rows, headline, rows_to_bookings, week_breakdown
from style import (
    BLUE,
    CSS,
    GUIDE_SECTIONS,
    INK,
    RED,
    YELLOW,
    category_colour,
    guide_html,
    hero_html,
    notice_html,
    sparkline_svg,
)

DATA = Path(__file__).resolve().parent.parent / "data"
DISCLAIMER = (
    "Planning estimate only. Results depend on the equipment figures, load factors and diversity "
    "assumptions entered. This is not a supply design or a quotation. Confirm with the supplier and "
    "a competent person."
)

st.set_page_config(
    page_title="SitePower", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed"
)
st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- state
def sample_project() -> Project:
    return project_from_json((DATA / "sample_project.json").read_text(encoding="utf-8"))


st.session_state.setdefault("version", 0)
st.session_state.setdefault("project", sample_project())
st.session_state.setdefault("loaded_upload", None)

# --------------------------------------------------------------------------- header (above the tabs)
hero_slot = st.empty()  # filled with the live demand sparkline once the estimate exists
hero_slot.markdown(
    hero_html(
        st.session_state["project"].name,
        st.session_state["project"].weeks,
        "",
        is_illustrative(find_library_path(DATA)),
    ),
    unsafe_allow_html=True,
)
# One notice: a flashing warning badge that drops down the text. Updated once the library in use is known.
notice_slot = st.empty()
notice_slot.markdown(
    notice_html(illustrative=is_illustrative(find_library_path(DATA))), unsafe_allow_html=True
)

(
    tab_overview,
    tab_project,
    tab_estimate,
    tab_compare,
    tab_cost,
    tab_calibrate,
    tab_export,
    tab_guide,
) = st.tabs(
    [
        "Overview",
        "Project",
        "Detail",
        "Compare",
        "Cost",
        "Calibrate",
        "Export & notes",
        "How to use",
    ]
)

# =========================================================================== GUIDE
with tab_guide:
    st.header("How to use SitePower")
    st.markdown(guide_html(), unsafe_allow_html=True)
    st.subheader("The full guide")
    for i, (title, body) in enumerate(GUIDE_SECTIONS):
        with st.expander(title, expanded=(i == 0)):
            st.markdown(body)

# =========================================================================== PROJECT
with tab_project:
    with st.expander("Load your own data, or reset to the sample", expanded=False):
        u1, u2, u3 = st.columns([2, 2, 1])
        lib_upload = u1.file_uploader("Equipment library (CSV)", type="csv", key="lib_upload")
        proj_upload = u2.file_uploader("Project (JSON)", type="json", key="proj_upload")
        u3.write("")
        if u3.button("Reset to the sample project"):
            st.session_state["project"] = sample_project()
            st.session_state["version"] += 1
            st.session_state["loaded_upload"] = None
            st.session_state["scales"] = None
            st.rerun()

    if proj_upload is not None and st.session_state["loaded_upload"] != proj_upload.file_id:
        try:
            st.session_state["project"] = project_from_json(proj_upload.getvalue().decode("utf-8"))
            st.session_state["loaded_upload"] = proj_upload.file_id
            st.session_state["version"] += 1
            st.session_state["scales"] = None
            st.rerun()
        except (ProjectError, UnicodeDecodeError) as exc:
            st.error(f"Could not read that project: {exc}")

    if lib_upload is not None:
        parsed = parse_equipment_csv(lib_upload.getvalue().decode("utf-8", errors="replace"))
        illustrative = False
    else:
        path = find_library_path(DATA)
        parsed = parse_equipment_csv(path.read_text(encoding="utf-8"))
        illustrative = is_illustrative(path)
    library_orig = parsed.library
    applied_scales: dict[str, float] | None = st.session_state.get("scales")
    # A calibration is applied on top of the user's own figures, never saved over them.
    library = apply_scales(library_orig, applied_scales) if applied_scales else library_orig

    notice_slot.markdown(notice_html(illustrative), unsafe_allow_html=True)
    for err in parsed.errors:
        st.error(f"Equipment CSV row {err.row}: {err.message}")
    if not library:
        st.error("The equipment library is empty or invalid, so nothing can be estimated.")
        st.stop()

    proj0: Project = st.session_state["project"]
    ver = st.session_state["version"]

    st.header("Project")
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    name = c1.text_input("Project name", proj0.name, key=f"name{ver}")
    weeks = int(c2.number_input("Weeks", 1, 156, proj0.weeks, 1, key=f"weeks{ver}"))
    base_kw = float(
        c3.number_input("Base load (kW)", 0.0, 10_000.0, proj0.base_load_kw, 0.5, key=f"bkw{ver}")
    )
    base_pf = float(
        c4.number_input(
            "Base power factor", 0.05, 1.0, proj0.base_power_factor, 0.01, key=f"bpf{ver}"
        )
    )

    groups = sorted(
        {e.diversity_group for e in library.values() if e.diversity_group}
        | set(proj0.group_diversity)
    )
    with st.expander("Group diversity factors (your assumptions)", expanded=False):
        st.caption(
            "Items in the same group are not all at peak together. 1.0 means no reduction. "
            "These are YOUR assumptions: the defaults are illustrative."
        )
        gdf = st.data_editor(
            pd.DataFrame(
                {"group": groups, "factor": [proj0.group_diversity.get(g, 1.0) for g in groups]}
            ),
            hide_index=True,
            disabled=["group"],
            column_config={
                "factor": st.column_config.NumberColumn(min_value=0.05, max_value=1.0, step=0.05)
            },
            key=f"gd{ver}",
            use_container_width=True,
        )
    diversity = {
        str(r["group"]): float(r["factor"])
        for r in gdf.to_dict("records")
        if r["factor"] == r["factor"]
    }

    st.header("Equipment schedule")
    st.caption(
        "Weeks are numbered from 1. Add a row for each hire; the same item can appear more than once."
    )
    sched = st.data_editor(
        pd.DataFrame(
            bookings_to_rows(proj0), columns=["equipment_id", "qty", "start_week", "end_week"]
        ),
        num_rows="dynamic",
        use_container_width=True,
        key=f"sched{ver}",
        column_config={
            "equipment_id": st.column_config.SelectboxColumn(
                "Equipment", options=sorted(library), required=True
            ),
            "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1),
            "start_week": st.column_config.NumberColumn(
                "From week", min_value=1, max_value=weeks, step=1
            ),
            "end_week": st.column_config.NumberColumn(
                "To week", min_value=1, max_value=weeks, step=1
            ),
        },
    )
    with st.expander("Equipment library in use (read-only)"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": e.id,
                        "name": e.name,
                        "category": e.category,
                        "rated kW": e.rated_kw,
                        "pf": e.power_factor,
                        "LF min": e.load_factor_min,
                        "LF mode": e.load_factor_mode,
                        "LF max": e.load_factor_max,
                        "group": e.diversity_group,
                        "source": e.source,
                    }
                    for e in library.values()
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    bookings, row_errors = rows_to_bookings(sched.to_dict("records"), library, weeks)
    for e in row_errors:
        st.error(f"Schedule row {e.row}: {e.message} (row ignored)")
    try:
        project = Project(name, weeks, tuple(bookings), diversity, base_kw, base_pf)
    except ValueError as exc:
        st.error(f"Project problem: {exc}")
        st.stop()
    st.success(
        "Project looks valid. Open the **Overview** tab to see the result.",
        icon=":material/check_circle:",
    )

# =========================================================================== ESTIMATE
with tab_estimate:
    st.header("Settings and detail")
    s1, s2 = st.columns(2)
    trials = s1.slider("Monte Carlo trials", 200, 10_000, 2_000, 200, key="trials")
    seed = int(
        s2.number_input("Random seed (same seed, same result)", 0, 1_000_000, 0, 1, key="seed")
    )

# =========================================================================== OVERVIEW
with tab_overview:
    o1, o2, o3 = st.columns([2, 2, 3])
    unit = o3.radio(
        "Show demand in (edit equipment on the Project tab)", ["kW", "kVA"], horizontal=True
    )
    headroom = (
        o1.slider("Headroom above the P90 peak", 0, 50, 15, 1, format="%d%%", key="headroom") / 100
    )
    slip = o2.slider(
        "Schedule slip (weeks)",
        0,
        8,
        0,
        1,
        key="slip",
        help="Each hire may start up to this many whole weeks late, drawn at random in every trial.",
    )

    det = estimate(project, library)
    mc = simulate(project, library, trials, seed, slip_weeks=slip)
    h = headline(det, mc, headroom)
    hero_slot.markdown(
        hero_html(
            name,
            weeks,
            sparkline_svg(mc.p10_kw, mc.p50_kw, mc.p90_kw, h.most_likely_peak_week - 1),
            illustrative,
        ),
        unsafe_allow_html=True,
    )

    if applied_scales:
        shown = sorted({round(v, 2) for v in applied_scales.values()})
        st.success(
            f"A calibration is applied: load factors scaled by {', '.join(f'x{v}' for v in shown)} "
            "(Calibrate tab). Your original equipment figures are unchanged.",
            icon=":material/tune:",
        )
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Peak, central estimate", f"{h.deterministic_peak_kw:,.0f} kW")
    m2.metric("Peak, median of trials", f"{h.p50_peak_kw:,.0f} kW")
    m3.metric("Peak, 90% below", f"{h.p90_peak_kw:,.0f} kW")
    m4.metric("Peak kVA (P90)", f"{h.p90_peak_kva:,.0f} kVA")
    m5.metric(
        "Recommended supply",
        f"{h.sizing.recommended_kva:,.0f} kVA"
        if h.sizing.recommended_kva is not None
        else "none listed",
    )
    st.caption(
        f"Required = {h.sizing.peak_kva:,.0f} kVA x (1 + {headroom:.0%}) = **{h.sizing.required_kva:,.0f} kVA**. "
        f"{h.sizing.note} Most likely peak week: **{h.most_likely_peak_week}**."
    )

    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Weekly demand")
        key = "kw" if unit == "kW" else "kva"
        df = pd.DataFrame(
            {
                "Week": range(1, weeks + 1),
                "P10": getattr(mc, f"p10_{key}"),
                "P50": getattr(mc, f"p50_{key}"),
                "P90": getattr(mc, f"p90_{key}"),
                "Central": getattr(det, key),
            }
        )
        legend_names = ["P10 to P90 band", "Median", "Central estimate"]
        series_colour = alt.Scale(domain=legend_names, range=[YELLOW, INK, RED])
        legend = alt.Legend(orient="right", title=None, symbolSize=60, labelFontSize=11)

        def layer(name: str) -> alt.Chart:
            """One legend entry per layer: a constant Series column drives the colour legend."""
            return alt.Chart(df.assign(Series=name)).encode(
                x=alt.X(
                    "Week:Q",
                    axis=alt.Axis(tickMinStep=1),
                    scale=alt.Scale(domain=[1, max(weeks, 2)], nice=False),
                ),
                color=alt.Color("Series:N", scale=series_colour, legend=legend),
            )

        band = (
            layer("P10 to P90 band")
            .mark_area(opacity=0.55)
            .encode(
                y=alt.Y("P10:Q", title=unit),
                y2="P90:Q",
                tooltip=["Week", "P10", "P50", "P90"],
            )
        )
        median = layer("Median").mark_line(strokeWidth=3).encode(y=alt.Y("P50:Q", title=unit))
        central = (
            layer("Central estimate")
            .mark_line(strokeDash=[6, 4], strokeWidth=2)
            .encode(y=alt.Y("Central:Q", title=unit))
        )
        pk = h.most_likely_peak_week
        peak_df = pd.DataFrame(
            {"Week": [pk], "v": [float(df["P50"].iloc[pk - 1])], "label": [f"Peak, week {pk}"]}
        )
        peak_rule = (
            alt.Chart(peak_df).mark_rule(color="#666666", strokeDash=[2, 3]).encode(x="Week:Q")
        )
        peak_dot = (
            alt.Chart(peak_df)
            .mark_point(filled=True, size=140, color=INK, stroke="#fff", strokeWidth=2)
            .encode(x="Week:Q", y=alt.Y("v:Q", title=unit))
        )
        peak_text = (
            alt.Chart(peak_df)
            .mark_text(align="left", dx=10, dy=-12, fontWeight="bold", color=INK)
            .encode(x="Week:Q", y=alt.Y("v:Q", title=unit), text="label:N")
        )
        st.altair_chart(
            (band + median + central + peak_rule + peak_dot + peak_text).properties(height=300),
            use_container_width=True,
        )
        st.caption(
            "Yellow band: P10 to P90. Black: median. Dashed red: central estimate. Dot: most likely peak week. "
            "**The band reflects load-factor uncertainty (plus schedule slip if set) only.**"
        )
    with col_r:
        st.subheader("Where the demand comes from")
        cats, mix_matrix = category_matrix(project, library)
        mix = pd.DataFrame(mix_matrix, columns=cats)
        mix["Base load"] = project.base_load_kw
        mix.insert(0, "Week", range(1, weeks + 1))
        mix_long = mix.melt("Week", var_name="Category", value_name="kW")
        order = [*cats, "Base load"]
        st.altair_chart(
            alt.Chart(mix_long)
            .mark_area(opacity=1, stroke="#ffffff", strokeWidth=1.5)
            .encode(
                x=alt.X(
                    "Week:Q",
                    title="Week",
                    axis=alt.Axis(tickMinStep=1),
                    scale=alt.Scale(domain=[1, max(weeks, 2)], nice=False),
                ),
                y=alt.Y("kW:Q", stack="zero", title="kW (central estimate)"),
                color=alt.Color(
                    "Category:N",
                    sort=order,
                    legend=alt.Legend(orient="right", title=None, symbolSize=60, labelFontSize=11),
                    scale=alt.Scale(domain=order, range=[category_colour(c) for c in order]),
                ),
                order=alt.Order("Category:N", sort="descending"),
                tooltip=["Week", "Category", alt.Tooltip("kW:Q", format=",.1f")],
            )
            .properties(height=300),
            use_container_width=True,
        )
        st.caption(
            "Central estimate split by equipment category, after group diversity; the layers add up to the dashed red line."
        )


# =========================================================================== DETAIL
with tab_estimate:
    st.subheader("Why is a week the size it is?")
    wk = st.slider("Week", 1, weeks, h.most_likely_peak_week)
    rows = week_breakdown(det, wk, library)
    st.caption(
        f"Week {wk}: central {det.kw[wk - 1]:,.1f} kW / {det.kva[wk - 1]:,.1f} kVA; "
        f"P10 to P90 {mc.p10_kw[wk - 1]:,.1f} to {mc.p90_kw[wk - 1]:,.1f} kW; base load {base_kw:,.1f} kW."
    )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("Only the base load is on site this week.")

    st.subheader("What drives that week?")
    drivers = peak_drivers(det, wk, library, diversity)
    if drivers:
        ddf = pd.DataFrame(
            {
                "Equipment": [d.name for d in drivers],
                "kW": [d.kw for d in drivers],
                "Share": [d.share for d in drivers],
                "Cumulative": [d.cumulative for d in drivers],
            }
        )
        dc1, dc2 = st.columns([3, 2])
        dc1.altair_chart(
            alt.Chart(ddf)
            .mark_bar(cornerRadiusEnd=8, color=BLUE)
            .encode(
                y=alt.Y("Equipment:N", sort="-x", title=None),
                x=alt.X("kW:Q", title="kW after diversity"),
                tooltip=[
                    "Equipment",
                    alt.Tooltip("kW:Q", format=".1f"),
                    alt.Tooltip("Share:Q", format=".0%"),
                ],
            )
            .properties(height=max(120, 34 * len(ddf))),
            use_container_width=True,
        )
        top = [d for d in drivers if d.cumulative - d.share < 0.8]
        dc2.markdown(
            f"**{len(top)} of {len(drivers)}** equipment types make up about 80% of week {wk}'s equipment "
            f"demand: {', '.join(d.name for d in top)}. Renting those smaller, or staggering them, lowers the peak most."
        )

    st.subheader("Phases")
    st.caption(
        "Group the weeks into phases to see each phase's own peak. Edit the table; weeks start at 1."
    )
    third = max(1, weeks // 3)
    phase_default = pd.DataFrame(
        [
            {"Phase": "Early", "From week": 1, "To week": third},
            {"Phase": "Middle", "From week": third + 1, "To week": max(third + 1, 2 * third)},
            {"Phase": "Late", "From week": min(weeks, 2 * third + 1), "To week": weeks},
        ]
    )
    pdf = st.data_editor(
        phase_default,
        num_rows="dynamic",
        use_container_width=True,
        key=f"phases{ver}_{weeks}",
    )
    phase_rows = [
        (str(r["Phase"] or ""), int(r["From week"]), int(r["To week"]))
        for r in pdf.to_dict("records")
        if r["From week"] == r["From week"] and r["To week"] == r["To week"]
    ]
    phase_res, phase_problems = phase_summary(phase_rows, det, mc.p90_kva)
    for msg in phase_problems:
        st.warning(msg)
    if phase_res:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Phase": r.name,
                        "Weeks": f"{r.start_week} to {r.end_week}",
                        "Peak, central (kW)": round(r.peak_kw, 1),
                        "Peak week": r.peak_week,
                        "P90 peak (kVA)": round(r.p90_peak_kva, 1),
                    }
                    for r in phase_res
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

# =========================================================================== COMPARE
with tab_compare:
    st.header("Compare two schedules")
    st.caption(
        "Scenario A is your schedule from the Project tab. Edit scenario B below (for example swap a tower crane "
        "for a mobile crane) and see the difference. B starts as a copy of A; if you change A afterwards, "
        "B is reset to the new copy."
    )
    cmp_rows = bookings_to_rows(project)
    sched_b = st.data_editor(
        pd.DataFrame(cmp_rows, columns=["equipment_id", "qty", "start_week", "end_week"]),
        num_rows="dynamic",
        use_container_width=True,
        key=f"schedb{ver}_{len(cmp_rows)}_{weeks}",
        column_config={
            "equipment_id": st.column_config.SelectboxColumn(
                "Equipment", options=sorted(library), required=True
            ),
            "qty": st.column_config.NumberColumn("Qty", min_value=1, step=1),
            "start_week": st.column_config.NumberColumn(
                "From week", min_value=1, max_value=weeks, step=1
            ),
            "end_week": st.column_config.NumberColumn(
                "To week", min_value=1, max_value=weeks, step=1
            ),
        },
    )
    bk_b, err_b = rows_to_bookings(sched_b.to_dict("records"), library, weeks)
    for e in err_b:
        st.error(f"Scenario B row {e.row}: {e.message} (row ignored)")
    project_b = Project(name, weeks, tuple(bk_b), diversity, base_kw, base_pf)
    det_b = estimate(project_b, library)
    mc_b = simulate(project_b, library, trials, seed, slip_weeks=slip)
    h_b = headline(det_b, mc_b, headroom)

    def _size(x: float | None) -> str:
        return f"{x:,.0f} kVA" if x is not None else "none listed"

    kwh_a, kwh_b = energy_kwh(det.kw, 50.0), energy_kwh(det_b.kw, 50.0)
    cmp_df = pd.DataFrame(
        {
            "": [
                "Peak, central (kW)",
                "Peak, 90% below (kW)",
                "Peak kVA (P90)",
                "Recommended supply",
                "Energy at 50 h/week (kWh)",
            ],
            "A (Project tab)": [
                f"{h.deterministic_peak_kw:,.0f}",
                f"{h.p90_peak_kw:,.0f}",
                f"{h.p90_peak_kva:,.0f}",
                _size(h.sizing.recommended_kva),
                f"{kwh_a:,.0f}",
            ],
            "B (edited)": [
                f"{h_b.deterministic_peak_kw:,.0f}",
                f"{h_b.p90_peak_kw:,.0f}",
                f"{h_b.p90_peak_kva:,.0f}",
                _size(h_b.sizing.recommended_kva),
                f"{kwh_b:,.0f}",
            ],
            "B minus A": [
                f"{h_b.deterministic_peak_kw - h.deterministic_peak_kw:+,.0f}",
                f"{h_b.p90_peak_kw - h.p90_peak_kw:+,.0f}",
                f"{h_b.p90_peak_kva - h.p90_peak_kva:+,.0f}",
                (
                    f"{h_b.sizing.recommended_kva - h.sizing.recommended_kva:+,.0f} kVA"
                    if h_b.sizing.recommended_kva is not None
                    and h.sizing.recommended_kva is not None
                    else "n/a"
                ),
                f"{kwh_b - kwh_a:+,.0f}",
            ],
        }
    )
    st.dataframe(cmp_df, hide_index=True, use_container_width=True)
    weeks_axis = list(range(1, weeks + 1))
    long = pd.concat(
        [
            pd.DataFrame({"Week": weeks_axis, "kW": mc.p50_kw, "Scenario": "A", "P90": mc.p90_kw}),
            pd.DataFrame(
                {"Week": weeks_axis, "kW": mc_b.p50_kw, "Scenario": "B", "P90": mc_b.p90_kw}
            ),
        ]
    )
    st.altair_chart(
        alt.Chart(long)
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("Week:Q", title="Week"),
            y=alt.Y("kW:Q", title="Median demand (kW)"),
            color=alt.Color("Scenario:N", scale=alt.Scale(domain=["A", "B"], range=[INK, BLUE])),
            tooltip=[
                "Week",
                "Scenario",
                alt.Tooltip("kW:Q", format=".1f"),
                alt.Tooltip("P90:Q", format=".1f"),
            ],
        )
        .properties(height=230),
        use_container_width=True,
    )
    delta = h_b.p90_peak_kva - h.p90_peak_kva
    if abs(delta) < 0.5:
        verdict = "the **same** as A (edit scenario B above to see a difference)"
    else:
        verdict = f"**{abs(delta):,.0f} kVA {'lower' if delta < 0 else 'higher'}** than A"
    st.info(f"Scenario B's P90 peak is {verdict}.", icon=":material/compare_arrows:")

# =========================================================================== COST
with tab_cost:
    st.header("Generator or grid connection?")
    st.caption(
        "A deliberately simple cost model on the central-estimate demand. Every price below is a placeholder: "
        "enter your own quotes, in one currency. It ignores standing charges, taxes, fuel delivery and maintenance."
    )
    k1, k2, k3 = st.columns(3)
    hours = k1.number_input("Working hours per week", 1.0, 168.0, 50.0, 1.0, key="c_hours")
    grid_conn = k2.number_input(
        "Grid connection, one-off", 0.0, 10_000_000.0, 25_000.0, 500.0, key="c_conn"
    )
    grid_rate = k3.number_input("Grid energy price per kWh", 0.0, 10.0, 0.25, 0.01, key="c_grate")
    k4, k5 = st.columns(2)
    gen_hire = k4.number_input(
        "Generator hire per week", 0.0, 1_000_000.0, 450.0, 10.0, key="c_hire"
    )
    gen_rate = k5.number_input("Generator fuel cost per kWh", 0.0, 10.0, 0.45, 0.01, key="c_frate")
    cost = compare_costs(det.kw, hours, grid_conn, grid_rate, gen_hire, gen_rate)
    q1, q2, q3 = st.columns(3)
    q1.metric("Grid total", f"{cost.grid_total:,.0f}")
    q2.metric("Generator total", f"{cost.generator_total:,.0f}")
    q3.metric(
        "Cheaper over the project",
        "Equal" if cost.cheaper == "equal" else cost.cheaper.capitalize(),
        f"saves {cost.saving:,.0f}",
        delta_color="off",
    )
    cdf = pd.concat(
        [
            pd.DataFrame(
                {"Week": weeks_axis, "Cumulative cost": cost.grid_cumulative, "Option": "Grid"}
            ),
            pd.DataFrame(
                {
                    "Week": weeks_axis,
                    "Cumulative cost": cost.generator_cumulative,
                    "Option": "Generator",
                }
            ),
        ]
    )
    st.altair_chart(
        alt.Chart(cdf)
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("Week:Q", title="Week"),
            y=alt.Y("Cumulative cost:Q"),
            color=alt.Color(
                "Option:N", scale=alt.Scale(domain=["Grid", "Generator"], range=[BLUE, RED])
            ),
        )
        .properties(height=230),
        use_container_width=True,
    )
    if cost.breakeven_week is None:
        st.info("The generator's cumulative cost never passes the grid's inside this project.")
    else:
        st.info(
            f"From week {cost.breakeven_week} the generator has cost more than the grid connection in total.",
        )
    st.caption(
        f"Size the generator for the recommended supply ({_size(h.sizing.recommended_kva)}), "
        "and treat this as a comparison of options, not a quotation."
    )

# =========================================================================== CALIBRATE
with tab_calibrate:
    st.header("Calibrate against metered data (optional)")
    st.caption(
        "Upload half-hourly meter readings (`timestamp,kw`). The estimate is compared with each week's maximum "
        "reading. Scales are fitted on the first 70% of the weeks that have data and judged only on the "
        "remaining weeks. Nothing is applied until you press Apply."
    )
    cc1, cc2, cc3 = st.columns([2, 1, 2])
    meter_upload = cc1.file_uploader("Metered data (CSV)", type="csv", key="meter_upload")
    use_sample = cc1.toggle("Use the SYNTHETIC sample instead", value=False, key="use_sample_meter")
    week1 = cc2.date_input("Date week 1 starts", date(2025, 1, 6), key="week1")
    mode_label = cc3.radio(
        "What to fit",
        ["One scale for all equipment (recommended)", "One scale per category (advanced)"],
        key="calib_mode",
    )
    mode = "global" if mode_label.startswith("One scale for all") else "category"

    meter_text: str | None = None
    synthetic = False
    if meter_upload is not None:
        meter_text = meter_upload.getvalue().decode("utf-8", errors="replace")
    elif use_sample:
        meter_text = (DATA / "sample_metered.synthetic.csv").read_text(encoding="utf-8")
        synthetic = True

    if meter_text is None:
        st.info(
            "Add metered data (or switch on the synthetic sample) to see how far the estimate is off."
        )
    else:
        parsed_m = parse_metered_csv(meter_text)
        for err in parsed_m.errors[:5]:
            st.error(f"Metered data row {err.row}: {err.message}")
        if len(parsed_m.errors) > 5:
            st.error(f"...and {len(parsed_m.errors) - 5} more problems.")
        if synthetic:
            st.warning(
                "**SYNTHETIC data.** Generated by this project, assuming the illustrative library under-estimates by "
                "about 25%. It demonstrates the mechanics. Results here say nothing about real-world accuracy.",
                icon=":material/science:",
            )
        peaks = weekly_peaks(parsed_m.samples, week1, weeks)
        try:
            result = calibrate(
                project, library_orig, peaks, mode=mode, trials=min(trials, 1000), seed=seed
            )
        except CalibrationError as exc:
            st.info(str(exc))
        else:
            for w in result.warnings:
                st.warning(w)
            st.markdown(
                f"Fitted on weeks {result.train_weeks[0] + 1} to {result.train_weeks[-1] + 1}; "
                f"judged on the {result.test_weeks and len(result.test_weeks)} held-out weeks "
                f"({', '.join(str(x + 1) for x in result.test_weeks)})."
            )
            b, a = result.before, result.after
            st.dataframe(
                pd.DataFrame(
                    {
                        "": [
                            "Mean error (kW)",
                            "Mean error (%)",
                            "Bias (kW, + = over-estimate)",
                            "Weeks inside P10 to P90",
                        ],
                        "Your figures": [
                            f"{b.mae:.1f}",
                            f"{b.mape:.1%}",
                            f"{b.bias:+.1f}",
                            f"{b.coverage:.0%}",
                        ],
                        "Proposed calibration": [
                            f"{a.mae:.1f}",
                            f"{a.mape:.1%}",
                            f"{a.bias:+.1f}",
                            f"{a.coverage:.0%}",
                        ],
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )
            scale_rows = [
                {
                    "Category": c,
                    "Proposed scale": f"x{s:.2f}",
                    "Note": (
                        "not enough data to fit" if c in result.not_identifiable
                        else "hit the limit" if c in result.at_bound else ""
                    ),
                }
                for c, s in sorted(result.scales.items())
            ]  # fmt: skip
            if mode == "category":
                st.dataframe(pd.DataFrame(scale_rows), hide_index=True, use_container_width=True)
            else:
                st.markdown(
                    f"**Proposed scale for all equipment: x{next(iter(result.scales.values())):.2f}**"
                )

            cal_det = estimate(project, result.library).kw
            orig_det = estimate(project, library_orig).kw
            cdf = (
                pd.DataFrame(
                    {
                        "Week": range(1, weeks + 1),
                        "Metered weekly maximum": [
                            None if np.isnan(v) else float(v) for v in peaks
                        ],
                        "Your figures": orig_det,
                        "Proposed calibration": cal_det,
                    }
                )
                .melt("Week", var_name="Series", value_name="kW")
                .dropna()
            )
            held = pd.DataFrame(
                {"start": [min(result.test_weeks) + 0.5], "end": [max(result.test_weeks) + 1.5]}
            )
            shade = (
                alt.Chart(held)
                .mark_rect(color=YELLOW, opacity=0.35)
                .encode(x=alt.X("start:Q", title="Week"), x2="end:Q")
            )
            lines = (
                alt.Chart(cdf)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "Week:Q",
                        title="Week",
                        axis=alt.Axis(tickMinStep=1),
                        scale=alt.Scale(domain=[1, max(weeks, 2)], nice=False),
                    ),
                    y=alt.Y("kW:Q", title="kW"),
                    color=alt.Color(
                        "Series:N",
                        scale=alt.Scale(
                            domain=[
                                "Metered weekly maximum",
                                "Your figures",
                                "Proposed calibration",
                            ],
                            range=[INK, RED, BLUE],
                        ),
                    ),
                    tooltip=["Week", "Series", "kW"],
                )
            )
            st.altair_chart(shade + lines, use_container_width=True)
            st.caption(
                "Grey area: the held-out weeks, the only ones the error figures above are computed on."
            )

            b1, b2 = st.columns(2)
            if b1.button(
                "Apply these scales to the estimate",
                type="primary",
                disabled=not result.improved,
                help="Disabled because the proposal did not reduce held-out error."
                if not result.improved
                else None,
            ):
                st.session_state["scales"] = dict(result.scales)
                st.rerun()
            if applied_scales and b2.button("Remove the calibration (back to my figures)"):
                st.session_state["scales"] = None
                st.rerun()

# =========================================================================== EXPORT
with tab_export:
    st.header("Export")
    e1, e2, e3, e4 = st.columns(4)
    e1.download_button(
        "Weekly profile (CSV)",
        profile_to_csv(project, det, mc),
        "sitepower-profile.csv",
        "text/csv",
    )
    e2.download_button(
        "Project (JSON)", project_to_json(project), "sitepower-project.json", "application/json"
    )
    assumptions = [
        f"Trials {trials}, seed {seed}, headroom {headroom:.0%}, schedule slip up to {slip} weeks.",
        f"Base load {base_kw:g} kW at power factor {base_pf:g}.",
        "Group diversity: "
        + (", ".join(f"{g} {f:g}" for g, f in sorted(diversity.items())) or "none"),
        "Calibration applied." if applied_scales else "No calibration applied.",
        "Sizing list is illustrative; confirm with the supplier.",
    ]
    e3.download_button(
        "Report (HTML, printable)",
        report_html(name, det, mc, h, assumptions, illustrative),
        "sitepower-report.html",
        "text/html",
    )
    e4.download_button(
        "Report (PDF)",
        report_pdf(name, det, mc, h, assumptions, illustrative),
        "sitepower-report.pdf",
        "application/pdf",
    )

    st.header("How this is calculated")
    st.markdown(
        "- **Per item:** qty x rated kW x load factor, in each week it is booked. kVA = kW / power factor.\n"
        "- **Diversity:** items in a group are summed, then multiplied by that group's factor.\n"
        "- **Base load** is added every week.\n"
        "- **Uncertainty:** each equipment type draws a load factor per trial from a triangular distribution "
        "(min, mode, max) using your seed; all bookings of a type share the draw (conservative for the peak).\n"
        "- **Sizing:** P90 peak kVA x (1 + headroom), then the smallest size in an *illustrative* list. "
        "Replace the list with the supplier's real options."
    )
    st.header("What to keep in mind")
    st.markdown(
        "- The equipment figures and the supply-size list are **illustrative placeholders** unless you loaded your own.\n"
        "- The uncertainty band reflects **load-factor uncertainty only**.\n"
        "- The metered example is **synthetic**: it shows how calibration works, not how accurate it is on a real site.\n"
        "- This is a planning estimate, not a supply design or a quotation."
    )
