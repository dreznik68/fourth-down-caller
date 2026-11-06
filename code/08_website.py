"""
08_website.py

What this script does:
    Puts the solved model into the website (GitHub Pages publishes docs/):
        docs/index.html         the tool. This script fills in its data block.
        docs/instructions.html  the printable how-to. This script fills in the
                                3 worked examples from the policy.
        docs/qr.png             QR code to the site
    The page does not run the dynamic program. It looks up solved values:
        - the best call for every (M, d, y, t), straight from policy.csv
        - for every (M, d), the win probability after each outcome of each call
          (they get the ball in each bucket, after our TD, after our FG)
    and multiplies them by the outcome chances to draw the probability tree.
    Before writing, the script rebuilds every win probability the page will
    show, the same way the page does, and checks it against policy.csv.

How to run (from the project root folder):
    python3 code/08_website.py

Needs:
    data/inputs/ and data/results/policy.csv (run 05_inputs.py and 06_solve.py first)
    segno (pip package) for the QR code
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import segno

from dp_model import (D_OUT, FG_EXTRA_YARDS, GRID, MISSED_FG_BACK, MISSED_FG_MAX, TOUCHBACK,
                      bi, converted_value, g, load_inputs, solve)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS = PROJECT_ROOT / "docs"
SITE_URL = "https://dreznik68.github.io/fourth-down-caller/"
SCALE = 1_000_000   # probabilities are stored as whole numbers in millionths
M_MAX = 8
CODE = {"go": "g", "fg": "f", "punt": "p", "any": "a"}
EXAMPLES = [  # (M, d, y, t): the 3 "Try this" situations, also the printed examples
    (4, 0, 55, 1),
    (2, -3, 30, 6),
    (2, 3, 65, 4),
]

# ---------------------------------------------------------------
# Solve once to get O, the win probability when they get the ball
# ---------------------------------------------------------------
inp = load_inputs()
d_vals, F, O = solve(inp, M_MAX)
policy = pd.read_csv(PROJECT_ROOT / "data" / "results" / "policy.csv")
bs = bi(inp["s_bucket"])
row = {d: i for i, d in enumerate(d_vals)}   # row of each d in the O arrays


def their_start(yardline):
    """Where they get the ball (their yardline_100) after a failed go, a missed
    kick, and a punt from this yardline. Same rules as dp_model.call_values."""
    fail = 100 - yardline
    miss = max(min(100 - (yardline + MISSED_FG_BACK), MISSED_FG_MAX), 1)
    ball = yardline - inp["punt"][min(max(bi(yardline) * 5, 35), 95)]
    punt = TOUCHBACK if ball < 1 else 100 - ball
    return fail, miss, punt


# Per (y, t) state: everything that does not depend on the score or M.
yt = []
for y, t in GRID:
    yardline = max(y, t)
    fail, miss, punt = their_start(yardline)
    td = int(t >= yardline)
    yt.append({
        "yardline": yardline, "td": td, "conv_b": 0 if td else bi(yardline - t),
        "fail_b": bi(fail), "miss_b": bi(miss), "punt_b": bi(punt),
        "c": inp["c"][t], "g": g(inp, yardline + FG_EXTRA_YARDS), "kick": yardline + FG_EXTRA_YARDS,
        "fail_start": fail, "miss_start": miss, "punt_start": round(punt),
    })

# Per (M, d): win probability after each outcome, with M - 1 possessions left.
#   ob[b]  they get the ball in bucket b (failed go, missed kick, punt)
#   cv[b]  we converted and the drive goes on from bucket b (TD, FG, or no score,
#          from D; same as dp_model.converted_value)
#   mk     we kicked a FG and they start at S
#   tdv    we scored a TD and they start at S
values = []
for M in range(1, M_MAX + 1):
    Ok = O[M - 1]
    conv = np.column_stack([converted_value(inp, Ok, b) for b in range(len(inp["d_td"]))])
    for d in range(-D_OUT, D_OUT + 1):
        r = row[d]
        values.append(list(Ok[r]) + list(conv[r]) + [Ok[row[d + 3], bs], Ok[row[d + 7], bs]])
values = np.rint(np.array(values) * SCALE).astype(int)

# Best call for every state, in the order the page indexes them: M, then d, then (y, t).
gi = {yt_: i for i, yt_ in enumerate(GRID)}
policy["order"] = ((policy["M"] - 1) * (2 * D_OUT + 1) + policy["d"] + D_OUT) * len(GRID) \
    + [gi[(y, t)] for y, t in zip(policy["y"], policy["t"])]
best = "".join(policy.sort_values("order")["best"].map(CODE))

guide = pd.read_csv(PROJECT_ROOT / "data" / "inputs" / "M_guide.csv")
data = {
    "scale": SCALE, "d_out": D_OUT, "m_max": M_MAX,
    "grid": GRID,
    "yt": [[s[k] for k in ["yardline", "td", "conv_b", "fail_b", "miss_b", "punt_b"]]
           + [round(s["c"] * SCALE), round(s["g"] * SCALE)]
           + [s[k] for k in ["kick", "fail_start", "miss_start", "punt_start"]] for s in yt],
    "v": values.ravel().tolist(),
    "best": best,
    "guide": guide[["minutes_left", "mean_M"]].round(3).values.tolist(),
    "examples": EXAMPLES,
}

# ---------------------------------------------------------------
# Check: rebuild every win probability the way the page does it
# ---------------------------------------------------------------
v = values.reshape(M_MAX, 2 * D_OUT + 1, 42) / SCALE
check = policy.copy()
k = check["M"].to_numpy() - 1
dd = check["d"].to_numpy() + D_OUT
s = [yt[gi[(y, t)]] for y, t in zip(check["y"], check["t"])]


def take(key):
    """One field of the per-(y, t) table, for every policy row."""
    return np.array([x[key] for x in s])


c_, g_ = np.rint(take("c") * SCALE) / SCALE, np.rint(take("g") * SCALE) / SCALE
v_conv = np.where(take("td") == 1, v[k, dd, 41], v[k, dd, 20 + take("conv_b")])
f_go = c_ * v_conv + (1 - c_) * v[k, dd, take("fail_b")]
f_fg = g_ * v[k, dd, 40] + (1 - g_) * v[k, dd, take("miss_b")]
f_punt = v[k, dd, take("punt_b")]
gap = max(np.abs(f_go - check["f_go"]).max(), np.abs(f_fg - check["f_fg"]).max(),
          np.abs(f_punt - check["f_punt"]).max())
print("========== Website data check ==========")
print(f"States: {len(check):,}. Largest gap between the page's win probabilities and "
      f"policy.csv: {gap:.1e}")
assert gap < 1e-5, "the page would not match policy.csv"
assert len(best) == len(policy)

# ---------------------------------------------------------------
# Write the data into docs/index.html
# ---------------------------------------------------------------
index = DOCS / "index.html"
html = index.read_text()
blob = json.dumps(data, separators=(",", ":"))
html, n = re.subn(r"/\*DATA_START\*/.*?/\*DATA_END\*/", lambda _: f"/*DATA_START*/{blob}/*DATA_END*/",
                  html, flags=re.S)
assert n == 1, "docs/index.html needs exactly one /*DATA_START*/ ... /*DATA_END*/ block"
index.write_text(html)
print(f"Wrote data into {index} ({index.stat().st_size / 1024:.0f} KB)")

# ---------------------------------------------------------------
# Worked examples for docs/instructions.html
# ---------------------------------------------------------------
NAMES = {"go": "Go for it", "fg": "Field goal", "punt": "Punt", "any": "Any call"}


def field_label(y):
    """Same field position names as the page's dropdown."""
    return f"opponent's {max(y, 1)} to {y + 4}" if y + 4 < 50 else f"your own {100 - (y + 4)} to {100 - y}"


def score_label(d):
    return "Tied" if d == 0 else (f"Up {d}" if d > 0 else f"Down {-d}")


def minutes_for(M):
    """Minutes left in the 4th quarter where M is the typical number of possessions."""
    mins = guide.loc[np.floor(guide["mean_M"] + 0.5) == M, "minutes_left"].tolist()
    if not mins:
        return "more than a full quarter left"
    lo, hi = min(mins), max(mins)
    return f"about {lo} minute{'s' if lo > 1 else ''} left" if lo == hi else f"about {lo} to {hi} minutes left"


cards = []
for i, (M, d, y, t) in enumerate(EXAMPLES, start=1):
    r = policy[(policy["M"] == M) & (policy["d"] == d) & (policy["y"] == y) & (policy["t"] == t)].iloc[0]
    probs = {c: r[f"f_{c}"] for c in ["go", "fg", "punt"]}
    order = sorted(probs, key=probs.get, reverse=True)
    t_text = "10 or more" if t == 10 else str(t)
    cards.append(f"""
      <div class="example">
        <h3>Example {i}: {score_label(d)}, 4th and {t_text}, {field_label(y)}</h3>
        <p class="inputs">Put in: <b>{M}</b> possessions left ({minutes_for(M)}), <b>{score_label(d)}</b>,
          <b>{field_label(y)}</b>, <b>{t_text}</b> yard{"s" if t != 1 else ""} to go.</p>
        <p class="answer">Best call: <b>{NAMES[r['best']]}</b>. It wins by {r['margin'] * 100:.1f} percentage points.</p>
        <p>Win chance: {', '.join(f"{NAMES[c].lower()} {probs[c]:.1%}" for c in order)}.</p>
      </div>""")

instructions = DOCS / "instructions.html"
text = instructions.read_text()
text, n = re.subn(r"<!-- EXAMPLES_START -->.*?<!-- EXAMPLES_END -->",
                  lambda _: "<!-- EXAMPLES_START -->" + "".join(cards) + "\n      <!-- EXAMPLES_END -->",
                  text, flags=re.S)
assert n == 1, "docs/instructions.html needs exactly one EXAMPLES block"
instructions.write_text(text)
print(f"Wrote 3 worked examples into {instructions}")

# ---------------------------------------------------------------
# QR code to the site
# ---------------------------------------------------------------
segno.make(SITE_URL, error="m").save(DOCS / "qr.png", scale=10, border=2, dark="#0b0b0b")
print(f"QR code for {SITE_URL} saved to {DOCS / 'qr.png'}")
for M, d, y, t in EXAMPLES:
    r = policy[(policy["M"] == M) & (policy["d"] == d) & (policy["y"] == y) & (policy["t"] == t)].iloc[0]
    print(f"  Example M={M}, d={d}, y={y}, t={t}: {r['best']} "
          f"(go {r['f_go']:.3f}, fg {r['f_fg']:.3f}, punt {r['f_punt']:.3f})")
