# SitePower: build plan (weekend scope)

## 0. How to work

- Build in the phases in section 8, in order. Commit at the end of each phase. Do not start a phase until the previous one's acceptance criteria pass.
- Engine first, test-driven: write the test, watch it fail, then implement. The UI comes only after the engine is green.
- **Never invent standards or equipment data.** Every default load figure in this repo is an *illustrative placeholder*, labelled as such in the data file and in the UI, with a `TODO(verify)`. The user supplies real figures (hire sheets, nameplates, their own site records).
- Keep the engine pure: no UI imports, no network, no hidden state. Randomness only through an explicit seed, so the same input and seed give the same output.
- Keep dependencies minimal (section 2). Ask at most one batched question per phase if blocked; otherwise decide and note it in `docs/DECISIONS.md`.
- Publishing: no personal or employer details in code, data, screenshots or commit metadata. CI workflow files need the GitHub `workflow` token scope; if it is not available, keep them in `docs/ci/`.

## 1. Product

**SitePower** estimates the **temporary electrical supply** a construction site needs, week by week, from the equipment it will use, and shows the uncertainty honestly.

**The problem.** Temporary supplies are often sized by rule of thumb or copied from the last job. Too small and the site stops; too large and the project pays for capacity and connection it never uses. A bottom-up estimate with an uncertainty band is more defensible.

**Users and moments**
- Site electrical / services engineer, at planning stage: enter the equipment hire schedule by build phase and get a demand profile (kW and kVA), the peak, and a recommended supply size with headroom.
- Same engineer, mid-project: upload metered half-hourly data and see how far the estimate was off, then recalibrate the load factors.
- Reviewer: every number traces to an equipment line, a load factor, a diversity assumption and a stated distribution.

**Positioning for recruiters (energy / engineering software).** A tested Python estimation library with honest uncertainty (Monte Carlo, seeded and reproducible), a calibration step evaluated on held-out time, a clean live demo, CI, and a plain statement of what the numbers can and cannot claim. It is not an AI toy and it does not pretend to be a design certificate.

**Non-goals (v1):** network/fault studies, cable or protection sizing (that is CircuitCheck's job), harmonics, DNO application forms, three-phase unbalance, user accounts, a database, any LLM feature.

## 2. Stack and repo

- Python 3.11+, `numpy`, `pandas`. UI: `streamlit` (free hosting on Streamlit Community Cloud, live demo from the GitHub repo). Charts: Streamlit's built-in Altair.
- Dev tools: `pytest`, `pytest-cov`, `ruff`, `mypy` (strict on the library).
- No backend server, no database. State lives in the Streamlit session; projects import/export as JSON and CSV.

```
SitePower/
  src/sitepower/            # pure library, fully typed and unit-tested
    models.py               # dataclasses: Equipment, Phase, Booking, Project, Estimate
    library.py              # load/validate the equipment CSV
    estimate.py             # deterministic week-by-week demand (kW, kVA)
    montecarlo.py           # seeded uncertainty: P10/P50/P90 curves, peak distribution
    sizing.py               # peak -> recommended supply size with headroom (illustrative size list)
    calibrate.py            # fit load-factor scale from metered data; time-split evaluation
    synth.py                # SYNTHETIC metered-data generator (clearly labelled)
    io.py                   # project JSON, CSV import/export, validation with row-level errors
  app/streamlit_app.py      # thin UI over the library
  data/
    equipment.illustrative.csv   # PLACEHOLDER values, labelled; user replaces
    sample_project.json
    sample_metered.synthetic.csv # SYNTHETIC, labelled
  tests/                    # golden, property and round-trip tests
  docs/ (DECISIONS.md, VALIDATION.md, ARCHITECTURE.md, screenshots/)
  .gitignore                # includes data/equipment.local.csv (a user's real figures, never committed)
  README.md
```

`data/equipment.local.csv`, if present, overrides the illustrative library (same pattern as CircuitCheck's local ampacity file).

## 3. Data model (`models.py`)

```python
@dataclass(frozen=True)
class Equipment:
    id: str
    name: str
    category: str  # e.g. 'lifting', 'welfare', 'lighting', 'tools'
    rated_kw: float
    power_factor: float  # 0 < pf <= 1
    load_factor_min: float  # fraction of rated kW actually drawn when in use
    load_factor_mode: float
    load_factor_max: float  # triangular distribution bounds, min <= mode <= max <= 1
    diversity_group: str | None  # items in a group are not all at peak together
    source: str  # where the figure came from; 'illustrative' by default


@dataclass(frozen=True)
class Booking:
    equipment_id: str
    qty: int
    start_week: int
    end_week: int  # inclusive, 0-based


@dataclass(frozen=True)
class Project:
    name: str
    weeks: int
    bookings: list[Booking]
    group_diversity: dict[str, float]  # group -> factor in (0, 1]; user supplied
    base_load_kw: float = 0.0  # site lighting/welfare baseline, user supplied
```

`Estimate`: per-week `kw`, `kva`, plus the contributing lines (for traceability).

## 4. Calculations to implement

All formulas appear in `docs/VALIDATION.md` with a worked hand example.

**4.1 Deterministic estimate (`estimate.py`)**
- For week *w*, item *i*: `P_i(w) = qty_i · rated_kw_i · LF_mode_i` if booked, else 0.
- Group diversity: items sharing a `diversity_group` are summed, then multiplied by that group's diversity factor (default 1.0, i.e. no reduction, if not provided). Ungrouped items add directly.
- `kW(w) = Σ groups + ungrouped + base_load_kw`.
- `kVA(w) = Σ_i P_i(w) / pf_i` (power factors differ per item; this is a stated conservative simplification: arithmetic kVA sum, not vector sum).
- Return the contributing lines per week so the UI can show "why".

**4.2 Uncertainty (`montecarlo.py`)**
- For each trial, draw each equipment type's load factor from a triangular(min, mode, max) distribution, then rerun 4.1. Use `numpy.random.Generator(PCG64(seed))`. `n_trials` default 2000.
- Output P10/P50/P90 per week, the distribution of the project **peak** kW and kVA, and the week the peak most often occurs.
- State in the UI and docs: the band reflects *load-factor uncertainty only*. It does not cover schedule slips, missing equipment or diversity errors.

**4.3 Sizing (`sizing.py`)**
- `required_kva = P90_peak_kva · (1 + headroom)`, headroom default 0.15 (a user setting, `TODO(verify)`).
- Recommend the smallest size from a configurable list of standard supply sizes (illustrative list, `TODO(verify)` against the supplier's real offerings). Never present it as a supplier quote.

**4.4 Calibration (`calibrate.py`)**
- Input: metered half-hourly kW with a timestamp, mapped to project weeks.
- Fit one scalar per equipment *category* that scales load factors, by bounded least squares on weekly peak kW (scikit-learn is not needed: use `numpy`/`scipy.optimize` only if `scipy` is added, else closed-form ridge on the category matrix). Bounds keep scales within a sane range (default 0.5 to 1.5).
- **Evaluate with a time split**: fit on the first 70% of weeks, report error on the last 30%. Report MAE, MAPE, bias, and the **coverage** of the P10 to P90 band on the held-out weeks. If fewer than 6 metered weeks exist, refuse to calibrate and say why.
- Never silently overwrite the user's figures: calibration produces a *proposed* set shown beside the originals, applied only on a button press, and undoable.

**4.5 Synthetic data (`synth.py`)**
- Generates plausible metered data from a *different* load-factor draw plus noise and occasional outages, so calibration has something to work on in the demo. Every file and chart that uses it is labelled **SYNTHETIC**. Metrics on synthetic data prove the mechanics only, and the README says so in the first screen of that section.

## 5. Golden tests (must pass before UI work)

Compute these by hand in the test file, with tolerances.
- Single item: 1 × 10 kW, LF mode 0.6, pf 0.8, booked weeks 2 to 4 → kW = 6.0 in weeks 2 to 4 and 0 elsewhere; kVA = 7.5.
- Two items in one group with diversity 0.7: (6 + 4) × 0.7 = 7.0 kW.
- Base load adds in every week, including weeks with no bookings.
- Overlapping bookings of the same item add quantities correctly.
- Monte Carlo: with `min = mode = max` the P10, P50 and P90 equal the deterministic value exactly.
- Monte Carlo reproducibility: same seed → identical arrays; different seed → different arrays.
- Triangular check: the sample mean over 20 000 draws is within 1% of `(min + mode + max) / 3`.
- Property tests (plain loops, no extra library): demand never decreases when quantity increases; P10 ≤ P50 ≤ P90 always; recommended size is monotone in peak kVA; no function returns NaN or negative demand for valid input.
- Sizing: peak 180 kVA, headroom 0.15 → 207 kVA → the smallest listed size ≥ 207.
- Calibration: on data generated with known scales (no noise) the fit recovers them within 1%; held-out error is reported on the last 30% of weeks only; fewer than 6 weeks raises a clear `CalibrationError`.
- IO: valid project round-trips JSON and CSV; a bad equipment row gives a row-numbered error and does not drop the others; load factors outside `0 < min ≤ mode ≤ max ≤ 1` are rejected.

Document each golden value and how it was derived in `docs/VALIDATION.md`.

## 6. UI (Streamlit, one page, left-to-right workflow)

1. **Project**: name, number of weeks, base load, diversity group factors.
2. **Equipment and schedule**: pick from the library (or upload your own CSV), set quantity and week range. A Gantt-style grid shows what is on site when.
3. **Estimate**: chart of weekly kW with the P10 to P90 band, peak marker, table of the contributing lines for any selected week, and the recommended supply size with the inputs that produced it.
4. **Calibrate** (needs metered data): upload CSV or load the **SYNTHETIC** sample; show estimate vs actual, error metrics on held-out weeks, band coverage, proposed scale per category, and an Apply button.
5. **Export**: CSV of the weekly profile, JSON of the project, and a one-page printable summary.

Rules: every number shows its unit; assumptions and the illustrative-data banner are always visible while placeholder data is active; colour is never the only signal; works on a laptop screen and a phone.

Disclaimer, shown in the app and on every export: "Planning estimate only. Results depend on the equipment figures, load factors and diversity assumptions entered. This is not a supply design or a quotation. Confirm with the supplier and a competent person."

## 7. Quality bar

- `ruff` clean, `mypy --strict` clean on `src/`, zero untyped public functions.
- Library test coverage ≥ 90% (`pytest --cov=sitepower`).
- Deterministic: all randomness through an explicit seed; a test proves it.
- No console errors or Streamlit exceptions on the sample project; the app starts from a clean checkout with `pip install -e .[dev]` then `streamlit run app/streamlit_app.py`.
- README claims only what was verified. Anything unverified (for example, behaviour on the free host after it sleeps) is stated as unverified.

## 8. Phases and acceptance criteria (weekend)

**Saturday morning, Phase 1: scaffold.** Repo, `pyproject.toml`, ruff/mypy/pytest config, a trivial passing test, `.gitignore`, empty package. *Accept:* `pytest`, `ruff check`, `mypy` pass on the skeleton.

**Saturday afternoon, Phase 2: engine core.** `models`, `library`, `io` validation, `estimate`, with the deterministic golden tests from section 5. *Accept:* those tests green.

**Saturday evening, Phase 3: uncertainty and sizing.** `montecarlo`, `sizing`, their golden and property tests. *Accept:* all engine tests green, coverage ≥ 90%.

**Sunday morning, Phase 4: UI.** Streamlit app with Project, Schedule, Estimate and Export; sample project loads; illustrative-data banner. *Accept:* sample project shows a chart with the band, the peak, a sizing recommendation, and exports a CSV.

**Sunday midday, Phase 5: calibration (stretch, cut if behind).** `synth`, `calibrate` with time-split evaluation, UI tab. *Accept:* synthetic example recovers scales, held-out metrics and coverage displayed, refusal on too little data. If time is short, ship without it and list it under "Roadmap" rather than half-finishing it.

**Sunday afternoon, Phase 6: ship.** Public GitHub repo, deploy on Streamlit Community Cloud, README with banner, screenshots and demo GIF, `docs/VALIDATION.md`, `docs/DECISIONS.md`. *Accept:* live URL loads the sample project; README checklist (section 9) complete.

## 9. README checklist (what recruiters read)

- One-line pitch, live demo link, CI badge (if workflows could be pushed), a hero banner and a GIF of load project → estimate → band → size → calibrate.
- "What it estimates" table: quantity, formula, assumption, what it does not cover.
- "How it's validated": golden tests with hand-worked examples, seeded reproducibility, held-out calibration, and where each value came from.
- Architecture: library ← UI, pure and seeded.
- **Limitations, stated plainly:** placeholder equipment data; band covers load-factor uncertainty only; synthetic metered data demonstrates mechanics, not real-world accuracy; not a supply design or quote; no network studies.
- How to load your own equipment figures (`data/equipment.local.csv` schema shown).
- Roadmap: schedule uncertainty, real metered-data connectors, scenario comparison, generator vs grid cost comparison, supplier size catalogues.

## 10. Open questions to settle before Phase 1

1. Does the user have **real** (non-confidential) equipment figures or site meter data to use as a second, non-synthetic example? If yes, it greatly strengthens the project; if not, the README must keep the synthetic caveat prominent.
2. Is CI wanted? If yes, the publishing account needs the GitHub `workflow` token scope, otherwise park workflows in `docs/ci/`.
3. Confirm which GitHub account the Streamlit Community Cloud sign-in will use.
4. Project name: `SitePower` is a working title. Check the name is free on GitHub before creating the repo.

## 11. Copyright and safety notes

- Do not copy tables from BS 7671, BS 7375, ENA/DNO documents or manufacturer catalogues into the repo. Reference them by name as places the user should verify against; keep all numeric defaults illustrative and local-overridable.
- Never describe output as a quotation, a design, or a compliance statement.
- No personal, employer or site-specific data in the repo, examples, screenshots or commit metadata.
