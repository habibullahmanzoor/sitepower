"""Build the static site that runs SitePower entirely in the visitor's browser (for GitHub Pages).

It uses stlite (Streamlit compiled to WebAssembly) loaded from a pinned CDN version. The page downloads the
Python files below and runs them inside the browser, so there is no server. Files keep their repository layout,
so `app/streamlit_app.py` finds `src/` and `data/` exactly as it does when run natively.

Usage:  python scripts/build_site.py [output_dir]      (default: site/)
Only the illustrative and sample data is copied. `data/equipment.local.csv` (a user's real figures) never is.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

STLITE_VERSION = "1.12.2"  # bundles Streamlit 1.65.0 and Pyodide 314 (Python 3.14)
CDN = f"https://cdn.jsdelivr.net/npm/@stlite/browser@{STLITE_VERSION}/build"
DATA_FILES = ("equipment.illustrative.csv", "sample_project.json", "sample_metered.synthetic.csv")

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SitePower</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23e6e51e'/%3E%3Cpath d='M18 4 8 18h7l-1 10 10-14h-7z' fill='%23fff'/%3E%3C/svg%3E" />
<meta name="description" content="Week-by-week temporary construction-site electrical demand, with an honest uncertainty band. Runs entirely in your browser. Planning estimate only." />
<link rel="stylesheet" href="__CDN__/stlite.css" />
<style>
  body { margin: 0; background: #f2f2f2; font-family: Inter, system-ui, sans-serif; }
  #note { max-width: 34rem; margin: 18vh auto 0; padding: 2rem 2.2rem; color: #000000; background: #fff;
          border: 1px solid #dfddd8; border-radius: 32px; }
  #note h2 { margin: 0 0 .6rem; font-size: 2.6rem; font-weight: 500; letter-spacing: -.05em; }
  #note h2 span { color: #000000; }
  #note p { color: #52545a; line-height: 1.5; }
  #note small { color: #898c94; }
  #bar { height: 6px; border-radius: 100px; background: #dfddd8; overflow: hidden; margin: 1.2rem 0; }
  #bar i { display: block; height: 100%; width: 35%; border-radius: 100px; background: #000000; animation: slide 1.4s ease-in-out infinite; }
  @keyframes slide { 0% { margin-left: -35%; } 100% { margin-left: 100%; } }
</style>
</head>
<body>
<div id="note">
  <h2>Site<span>Power</span></h2>
  <div id="bar"><i></i></div>
  <p>Starting Python in your browser. The first visit downloads a few tens of MB, so it can take a little while.
  Nothing you enter leaves your device.</p>
  <small>Planning estimate only. Not a supply design or a quotation.</small>
  <noscript><p>This app needs JavaScript.</p></noscript>
</div>
<div id="root"></div>
<script type="module">
  import { mount } from "__CDN__/stlite.js";
  const FILES = __FILES__;
  const files = {};
  for (const path of FILES) files[path] = { url: path };
  document.getElementById("note").style.display = "block";
  mount(
    {
      entrypoint: "app/streamlit_app.py",
      requirements: ["numpy"],
      files,
      disableProgressToasts: true,
      streamlitConfig: {
        "theme.base": "light",
        "theme.primaryColor": "#000000",
        "theme.backgroundColor": "#f2f2f2",
        "theme.secondaryBackgroundColor": "#ffffff",
        "theme.textColor": "#000000",
        "client.toolbarMode": "minimal",
      },
    },
    document.getElementById("root"),
  );
  // hide the note once the app has rendered something
  const obs = new MutationObserver(() => {
    if (document.querySelector('[data-testid="stApp"], .stApp')) {
      document.getElementById("note").style.display = "none";
      obs.disconnect();
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
</script>
</body>
</html>
"""


def collect(root: Path) -> list[str]:
    """Relative POSIX paths of every file the in-browser app needs. Raises if something required is missing."""
    paths: list[str] = []
    for name in ("streamlit_app.py", "style.py"):
        app = root / "app" / name
        if not app.is_file():
            raise FileNotFoundError(f"missing {app}")
    paths += ["app/streamlit_app.py", "app/style.py"]
    pkg = root / "src" / "sitepower"
    if not pkg.is_dir():
        raise FileNotFoundError(f"missing {pkg}")
    paths += sorted(p.relative_to(root).as_posix() for p in pkg.glob("*.py"))
    for name in DATA_FILES:
        f = root / "data" / name
        if not f.is_file():
            raise FileNotFoundError(f"missing {f}")
        paths.append(f"data/{name}")
    return paths


def build(root: Path, out: Path) -> list[str]:
    files = collect(root)
    if out.exists():
        shutil.rmtree(out)
    for rel in files:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, dest)
    html = INDEX.replace("__CDN__", CDN).replace("__FILES__", json.dumps(files, indent=2))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return files


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "site"
    files = build(root, out)
    print(f"built {out} with {len(files)} files (stlite {STLITE_VERSION})")


if __name__ == "__main__":
    main()
