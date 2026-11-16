# Validation

Every expected value in the tests is worked by hand from the formulas below. None come from a standards table or a supplier catalogue. Equipment figures used in tests are invented round numbers chosen so the arithmetic can be checked on paper.

## Formulas

For booking *b* of item *i* active in week *w*: `P = qty x rated_kw x load_factor`, and `S = P / power_factor`.

Items in a diversity group are summed, then multiplied by that group's factor (default 1.0). Ungrouped items add directly. The base load adds `base_load_kw` to kW and `base_load_kw / base_power_factor` to kVA every week.

kVA is the arithmetic sum of per-item `P / pf` (a conservative simplification: it does not add phasors).

## Deterministic golden values (`tests/test_estimate.py`)

| Case | Working | Expected |
|---|---|---|
| 1 x 10 kW, load factor 0.6, pf 0.8, weeks 2 to 4 | 10 x 0.6 = 6.0 kW; 6.0 / 0.8 = 7.5 kVA | 6.0 kW and 7.5 kVA in weeks 2 to 4, else 0 |
| 3 units of the above | 3 x 6.0 | 18.0 kW |
| Group of (6.0 kW) + (10 kW x 0.4 = 4.0 kW), diversity 0.7 | (6 + 4) x 0.7 | 7.0 kW; kVA (7.5 + 5.0) x 0.7 = 8.75 |
| Base load 5 kW, pf 0.9 | 5 / 0.9 | 5 kW and 5.556 kVA in every week, added to booked weeks |
| 1 unit weeks 0 to 2 plus 2 units weeks 2 to 3 | week 2 has 3 units | 18 kW in week 2 |

## Uncertainty (`tests/test_montecarlo_sizing.py`)

- **Zero-width distribution** (min = mode = max): P10, P50 and P90 equal the deterministic estimate to 1e-12. This holds because one function (`estimate.demand`) serves both paths.
- **Triangular mean**: for min 0.2, mode 0.5, max 0.9 the mean is (0.2 + 0.5 + 0.9) / 3 = 0.5333; the sample mean of 20,000 draws on a 10 kW item is within 1% of 5.333 kW.
- **Reproducibility**: the same seed gives identical arrays; a different seed does not. Draws are made in sorted equipment-id order, and only for equipment actually booked, so unused library items never change a result.
- **Ordering**: P10 <= P50 <= P90 for every week, in kW and kVA.
- **Peak-week counts** sum to the number of trials and only fall in booked weeks.
- **No NaN or negative values** for valid input.

### What the band does and does not mean

Each equipment *type* draws one load factor per trial, shared by all its bookings (perfect correlation, deliberately conservative for the peak). The band reflects **load-factor uncertainty only**. It does not cover schedule slips, missing equipment, wrong diversity factors or wrong rated powers.

## Sizing

`required = peak_kva x (1 + headroom)`; the recommendation is the smallest listed size at or above it. Golden case: 180 kVA with 0.15 headroom is 207 kVA, so the recommendation is the smallest listed size at or above 207. The size list is an **illustrative placeholder** (`TODO(verify)` with the supplier). If the requirement exceeds the largest listed size, no size is recommended and the result says so.

## Not validated

- No equipment figure in this repository has been checked against a real site or catalogue. The bundled library and the metered example are illustrative or synthetic and labelled so.
- The model has not been compared with real metered data. Its purpose is a transparent, reproducible planning estimate, not a prediction of any specific site.

## Calibration (`tests/test_calibrate.py`)

Weekly demand is linear in the load factors, so a scale can be fitted by least squares. The model's weekly kW is compared with the weekly **maximum** of the metered half-hourly kW.

- **Known scales are recovered** from noise-free data (1% tolerance) in both modes: one global scale, and one scale per category.
- **Held-out evaluation.** Weeks with data are split in time order: the first 70% (rounded down) fit, the rest are held out. Every metric (mean error, mean % error, bias, coverage of the P10 to P90 band) uses the held-out weeks only. A test recomputes the "before" error by hand on exactly those weeks.
- **Refusals.** Fewer than 6 metered weeks, a length mismatch, an invalid mode, or no equipment load in the fitting weeks raise a `CalibrationError` that says why.
- **Honest outcome.** If the proposal does not reduce held-out error, the result says "Do not apply it" and the app disables the Apply button.

### What the evidence changed

The first design fitted one scale per category by default. Measured on the bundled synthetic example, that was badly conditioned: with 11 fitting weeks and 7 categories (two never on site in that window), categories that switch on and off together cannot be separated. Scale errors ranged from 3% to 35% depending on the shrinkage setting, and held-out error got *worse* in several settings. So the default is now **one global scale** (a single, always-identifiable parameter), and per-category fitting is an advanced option that warns when the weeks are too few for the number of scales fitted.

On the bundled synthetic example the global mode reduces held-out mean error from 14.9 kW to 1.8 kW (17.4% to 2.1%) and brings the band coverage from 0% to 100%.

### What that does and does not show

The synthetic metered data was **generated by this project** from the same model, assuming the illustrative library under-estimates by about 25%. A model that works on data it generated itself demonstrates the mechanics and nothing more. It says nothing about accuracy on a real site. Real metered data, and several real projects, would be needed before claiming any accuracy.
