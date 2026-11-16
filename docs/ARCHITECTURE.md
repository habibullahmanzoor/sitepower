# Architecture

```
              data/*.csv|json                 upload / sidebar
                    |                               |
                    v                               v
  +--------------------------------------------------------------+
  |  app/streamlit_app.py   (thin page: widgets, charts, exports) |
  +------------------------------+-------------------------------+
                                 | plain data in, results out
  +------------------------------v-------------------------------+
  |  src/sitepower   (pure library: typed, tested, no UI imports) |
  |   models  library  io  estimate  montecarlo  sizing          |
  |   calibrate  synth  uimodel                                   |
  +---------------------------------------------------------------+
```

- **One calculation path.** `estimate.demand` serves both the deterministic estimate and every Monte Carlo trial, so a zero-width distribution reproduces the deterministic result exactly (tested).
- **Seeded randomness only.** Every random draw comes from `numpy.random.Generator(PCG64(seed))`; the same project, library and seed give identical output (tested). No hidden global state.
- **The page contains no calculations.** `uimodel` holds the conversions and headline numbers so they are typed and unit-tested; the page only draws them.
- **Nothing overwrites the user's figures.** A calibration is a layer applied on top of the library, shown in a banner, and removable.
- **Local overrides.** `data/equipment.local.csv` (git-ignored) replaces the illustrative library.
- **No server.** scripts/build_site.py copies the app, library and sample data into site/ and writes an index.html that loads a pinned stlite from a CDN. The browser runs the same Python files, so there is one code path, native or static.
- **No LLM, no database.** The app is a calculator. After the page has loaded, the only network traffic is the one-off download of the runtime; nothing you enter is sent anywhere.
