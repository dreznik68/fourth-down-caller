"""
06_solve.py

What this script does:
    Solves the fourth-down dynamic program in PLAN.md by backward recursion
    and saves the best call for every situation:
        data/results/policy.csv    one row per (M, d, y, t): win probability of
                                   go, fg, and punt, the best call ("any" if all
                                   three are equal), and its margin over the next best
        outputs/DP_Hand_Check.xlsx the M = 1 hand check, every Table cell a live
                                   Excel formula
    Then it recalculates the workbook with LibreOffice, confirms it matches the
    solver, and runs the sanity checks.

How to run (from the project root folder):
    python3 code/06_solve.py

Needs:
    data/inputs/ (run 05_inputs.py first)
    LibreOffice in /Applications (only for the hand check recalculation)

The model, in the solver's terms:
    k = possessions left in the game, counting the current one (k = M at the
        4th down we are deciding). Ours and theirs alternate.
    d = our score minus theirs. f*(d) at the end = 1 if d > 0, 0.5 if d = 0, 0 if d < 0.
    Three value tables, each a win probability:
        W[k](d)       our possession starts at S, k possessions left
        O[k](d, y)    their possession starts at y, k possessions left
        F[k](d, y, t) we face 4th down at y with t to go, k possessions left
    W uses A (how our possession from S goes), O uses D (how their drive goes),
    and F tries go, fg, and punt, each leading to their possession O[k - 1].

Field position:
    y in policy.csv is the 5-yard bucket name (40 means yardline_100 40 to 44).
    The formulas use the bucket's lowest yard as the exact yardline, so y = 40
    kicks from 57 yards. If t is larger than that (only possible inside the 10,
    for example 4th and goal from the 3 is bucket 0), the yardline is t, which
    makes it 4th and goal. The yardline used is saved in the yardline column.
"""

import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IN_DIR = PROJECT_ROOT / "data" / "inputs"
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
RESULTS_DIR.mkdir(exist_ok=True)
HAND_CHECK_FILE = PROJECT_ROOT / "outputs" / "DP_Hand_Check.xlsx"
LIBREOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")

M_MAX = 8                       # possessions left: 1 to 8
D_OUT = 21                      # policy.csv covers d from -21 to +21
CALLS = ["go", "fg", "punt"]
N_BUCKETS = 20                  # field position buckets 0, 5, ..., 95
FG_EXTRA_YARDS = 17             # kick distance = yardline + 17
MISSED_FG_BACK = 7              # a missed kick gives the ball back 7 yards behind the line
MISSED_FG_MAX = 80              # ...but never worse for them than their own 20
TOUCHBACK = 80                  # a punt into the end zone gives them the ball at their 20

# Scores can move by at most 7 per possession, so d from -21 to +21 needs
# room for 8 more possessions. Outside this range the game is already decided.
D_LIM = D_OUT + 7 * M_MAX
d_vals = np.arange(-D_LIM, D_LIM + 1)
idx = np.arange(len(d_vals))

# ---------------------------------------------------------------
# Load the inputs (probabilities are recomputed from the counts so they are exact)
# ---------------------------------------------------------------
c_df = pd.read_csv(IN_DIR / "c_conversion.csv")
C = dict(zip(c_df["t"], c_df["conversions"] / c_df["attempts"]))

g_fit = pd.read_csv(IN_DIR / "logistic_fits.csv").set_index("fit").loc["g_fieldgoal"]
G_A, G_B = g_fit["intercept_a"], g_fit["slope_b"]

p_df = pd.read_csv(IN_DIR / "P_punt.csv")
P = dict(zip(p_df["start_bucket"], p_df["mean_net_yards"]))

d_df = pd.read_csv(IN_DIR / "D_drive.csv").set_index("start_bucket").sort_index()
assert list(d_df.index) == list(range(0, 100, 5)), "D_drive.csv must have buckets 0 to 95"
D_TD = (d_df["td_drives"] / d_df["drives"]).to_numpy()
D_FG = (d_df["fg_drives"] / d_df["drives"]).to_numpy()
D_NONE = 1 - D_TD - D_FG

a_df = pd.read_csv(IN_DIR / "A_our_possession.csv")
a_df["p"] = a_df["drives"] / a_df["drives"].sum()
A_TD, A_FG, A_NONE = (a_df.loc[a_df["outcome"] == o, "p"].sum() for o in ["td", "fg", "none"])
A_CELLS = a_df.loc[a_df["outcome"] == "fourth_down", ["y", "t", "p"]].astype(
    {"y": int, "t": int}).itertuples(index=False)
A_CELLS = list(A_CELLS)

s_info = dict(line.strip().split("=") for line in open(IN_DIR / "S_start.txt")
              if "=" in line and not line.startswith("#"))
S_BUCKET = int(s_info["S_bucket"])


def bi(yardline):
    """Bucket index (0 to 19) of a yardline: 1 to 4 -> 0, 40 to 44 -> 8."""
    return min(int(yardline // 5), N_BUCKETS - 1)


BS = bi(S_BUCKET)  # bucket index of S


def g(kick_distance):
    """Field goal make chance from the logistic fit."""
    return 1 / (1 + math.exp(-(G_A + G_B * kick_distance)))


def shift(v, s):
    """v at d + s for every d (clamped at the edges, where the game is decided)."""
    return v[np.clip(idx + s, 0, len(idx) - 1)]


def terminal():
    """Boundary condition: win = 1, tie = 0.5, loss = 0."""
    return np.where(d_vals > 0, 1.0, np.where(d_vals == 0, 0.5, 0.0))


def their_possession(W_next):
    """O[k](d, y) for every start bucket: their drive ends in TD (-7), FG (-3),
    or no score, then we start at S with one fewer possession left (W_next)."""
    return (D_TD[None, :] * shift(W_next, -7)[:, None]
            + D_FG[None, :] * shift(W_next, -3)[:, None]
            + D_NONE[None, :] * W_next[:, None])


def call_values(O_next, yardline, t):
    """Win probability of go, fg, and punt from 4th and t at an exact yardline.
    O_next[d, b] = win probability when they get the ball in bucket b next."""
    at_S = O_next[:, BS]  # they start at S (after any score by us)

    # go: convert with prob c(t). Converted: TD if t = yardline, otherwise
    # the rest of the drive follows D(yardline - t). Failed: they start at 100 - y.
    if t >= yardline:
        converted = shift(at_S, 7)
    else:
        b = bi(yardline - t)
        converted = D_TD[b] * shift(at_S, 7) + D_FG[b] * shift(at_S, 3) + D_NONE[b] * at_S
    failed = O_next[:, bi(100 - yardline)]
    go = C[t] * converted + (1 - C[t]) * failed

    # fg: make with prob g(y + 17) and they start at S. Missed: they start at
    # the spot of the kick (y + 7 from their goal), or their 20 if that is better.
    make = g(yardline + FG_EXTRA_YARDS)
    missed_spot = max(min(100 - (yardline + MISSED_FG_BACK), MISSED_FG_MAX), 1)
    fg = make * shift(at_S, 3) + (1 - make) * O_next[:, bi(missed_spot)]

    # punt: the ball moves P(y) yards (punts from inside the 40 use bucket 35).
    # If that would carry past the goal line, it is a touchback at their 20.
    ball = yardline - P[min(max(bi(yardline) * 5, 35), 95)]
    their_start = TOUCHBACK if ball < 1 else 100 - ball
    punt = O_next[:, bi(their_start)]
    return np.vstack([go, fg, punt])


# Policy states: every bucket y and yards to go t that can happen there
# (t can be at most the bucket's highest yard, so bucket 0 only has t = 1 to 4).
GRID = [(y, t) for y in range(0, 100, 5) for t in range(1, 11) if t <= y + 4]
assert all((y, t) in GRID for y, t, _ in A_CELLS), "every A cell must be a policy state"

# ===============================================================
# Backward recursion over possessions left, k = 1 to M_MAX
# ===============================================================
W = [terminal()]                                    # W[0]: game over
O = [np.tile(terminal()[:, None], (1, N_BUCKETS))]  # O[0]: game over
F = {}                                              # F[(k, y, t)] = 3 x len(d) array
for k in range(1, M_MAX + 1):
    best = {}
    for y, t in GRID:
        F[(k, y, t)] = call_values(O[k - 1], max(y, t), t)
        best[(y, t)] = F[(k, y, t)].max(axis=0)
    at_S = O[k - 1][:, BS]
    W.append(A_TD * shift(at_S, 7) + A_FG * shift(at_S, 3) + A_NONE * at_S
             + sum(p * best[(y, t)] for y, t, p in A_CELLS))
    O.append(their_possession(W[k - 1]))

# ---------------------------------------------------------------
# Save policy.csv
# ---------------------------------------------------------------
keep = np.abs(d_vals) <= D_OUT
blocks = []
for (k, y, t), vals in F.items():
    v = np.round(vals[:, keep], 12)        # round so exact ties count as ties
    order = np.sort(v, axis=0)
    # best = the call with the highest win probability. If all three are exactly
    # equal (the game is already decided, like up 10 with M = 1), best = "any".
    best = np.where(order[-1] == order[0], "any", np.array(CALLS)[v.argmax(axis=0)])
    blocks.append(pd.DataFrame({
        "M": k, "d": d_vals[keep], "y": y, "t": t, "yardline": max(y, t),
        "f_go": v[0], "f_fg": v[1], "f_punt": v[2],
        "best": best,
        "margin": order[-1] - order[-2],    # best minus second best
    }))
policy = pd.concat(blocks).sort_values(["M", "d", "y", "t"]).reset_index(drop=True)
policy.round(6).to_csv(RESULTS_DIR / "policy.csv", index=False)

print("========== policy.csv ==========")
print(f"Rows: {len(policy):,} = {M_MAX} values of M x {2 * D_OUT + 1} values of d "
      f"x {len(GRID)} (y, t) states")
print("Best call counts by M:")
print(pd.crosstab(policy["M"], policy["best"]).to_string())


def lookup(M, d, y, t):
    """One row of the policy as a dict."""
    return policy[(policy["M"] == M) & (policy["d"] == d) & (policy["y"] == y)
                  & (policy["t"] == t)].iloc[0]


# ===============================================================
# Hand check workbook: M = 1, d = -3, y = 40, 35, 30, t = 1, 2, 5
# ===============================================================
HC_D, HC_Y, HC_T = -3, [40, 35, 30], [1, 2, 5]
states = [(HC_D, y, t) for y in HC_Y for t in HC_T]
FONT, BOLD = Font(name="Arial", size=11), Font(name="Arial", size=11, bold=True)


def write_row(ws, row, values, bold=False, fmt=None):
    """Write a list of values (or formulas) across one row."""
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = BOLD if bold else FONT
        if fmt and isinstance(value, str) and value.startswith("="):
            cell.number_format = fmt


wb = Workbook()
inp = wb.active
inp.title = "Inputs"
write_row(inp, 1, ["Inputs for the M = 1 hand check (counts from data/inputs, "
                   "probabilities are formulas)"], bold=True)

# c(t) for the t values used. Rows 3 to 6.
write_row(inp, 3, ["t", "attempts", "conversions", "c(t)"], bold=True)
for i, t in enumerate(HC_T):
    r = c_df[c_df["t"] == t].iloc[0]
    write_row(inp, 4 + i, [t, int(r["attempts"]), int(r["conversions"]), f"=C{4 + i}/B{4 + i}"],
              fmt="0.0000")
C_RANGE = "$A$4:$D$6"

# g logistic fit. Rows 8 to 9.
write_row(inp, 8, ["g fit intercept a", G_A], bold=False)
write_row(inp, 9, ["g fit slope b", G_B], bold=False)

# D for the buckets of y - t that the states land in. Rows 11 to 14.
d_buckets = sorted({bi(y - t) * 5 for _, y, t in states})
write_row(inp, 11, ["D start bucket", "drives", "TD drives", "FG drives", "P_TD", "P_FG", "P_none"],
          bold=True)
for i, b in enumerate(d_buckets):
    r, row = d_df.loc[b], 12 + i
    write_row(inp, row, [b, int(r["drives"]), int(r["td_drives"]), int(r["fg_drives"]),
                         f"=C{row}/B{row}", f"=D{row}/B{row}", f"=1-E{row}-F{row}"], fmt="0.0000")
D_RANGE = f"$A$12:$G${11 + len(d_buckets)}"

# One row per state with every number its formulas use. Rows 17 onward.
STATE_ROW0 = 17
write_row(inp, 16, ["state", "d", "y", "t", "c(t)", "y - t", "D bucket", "P_TD", "P_FG", "P_none",
                    "kick distance", "g(y + 17)", "f*_2(d + 7)", "f*_2(d + 3)", "f*_2(d)"], bold=True)
def boundary(x):
    """Excel formula for the boundary condition f*_2 at score difference x."""
    return f"=IF({x}>0,1,IF({x}=0,0.5,0))"


for i, (d, y, t) in enumerate(states):
    r = STATE_ROW0 + i
    write_row(inp, r, [
        i + 1, d, y, t,
        f"=VLOOKUP(D{r},{C_RANGE},4,FALSE)",
        f"=C{r}-D{r}",
        f"=5*INT(F{r}/5)",
        f"=VLOOKUP(G{r},{D_RANGE},5,FALSE)",
        f"=VLOOKUP(G{r},{D_RANGE},6,FALSE)",
        f"=VLOOKUP(G{r},{D_RANGE},7,FALSE)",
        f"=C{r}+17",
        f"=1/(1+EXP(-($B$8+$B$9*K{r})))",
        boundary(f"B{r}+7"), boundary(f"B{r}+3"), boundary(f"B{r}"),
    ], fmt="0.0000")
note_row = STATE_ROW0 + len(states) + 1
write_row(inp, note_row, ["f*_2 is the boundary condition: 1 if d > 0, 0.5 if d = 0, 0 if d < 0. "
                          "With M = 1 there is no stage after ours."])

# Table tab in the professor's format. Every cell is a formula from Inputs.
tab = wb.create_sheet("Table")
write_row(tab, 1, ["s_1 = (d, y, t)", "f_1(s_1, go)", "f_1(s_1, fg)", "f_1(s_1, punt)",
                   "f*_1(s_1)", "x*_1"], bold=True)
for i in range(len(states)):
    r, s = 2 + i, STATE_ROW0 + i
    write_row(tab, r, [
        f'="("&Inputs!B{s}&", "&Inputs!C{s}&", "&Inputs!D{s}&")"',
        f"=Inputs!E{s}*(Inputs!H{s}*Inputs!M{s}+Inputs!I{s}*Inputs!N{s}+Inputs!J{s}*Inputs!O{s})"
        f"+(1-Inputs!E{s})*Inputs!O{s}",
        f"=Inputs!L{s}*Inputs!N{s}+(1-Inputs!L{s})*Inputs!O{s}",
        f"=Inputs!O{s}",
        f"=MAX(B{r}:D{r})",
        f'=IF(B{r}=E{r},"go",IF(C{r}=E{r},"fg","punt"))',
    ], fmt="0.0000")

for ws in (inp, tab):
    ws.freeze_panes = "A2"
    for col in ws.columns:
        width = max(len(str(c.value)) if c.value is not None and not str(c.value).startswith("=")
                    else 8 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 18)
inp.column_dimensions["A"].width = 18
tab.column_dimensions["A"].width = 18
HAND_CHECK_FILE.parent.mkdir(exist_ok=True)
wb.save(HAND_CHECK_FILE)

# ---------------------------------------------------------------
# Recalculate with LibreOffice and compare with the solver
# ---------------------------------------------------------------
print("\n========== Hand check (M = 1, d = -3) ==========")
solver_rows = [lookup(1, d, y, t) for d, y, t in states]
if not LIBREOFFICE.exists():
    print("LibreOffice not found in /Applications, so the recalculation check was skipped.")
else:
    work_dir = Path(tempfile.mkdtemp())
    profile = work_dir / "profile" / "user"
    profile.mkdir(parents=True)
    # Tell LibreOffice to always recalculate formulas when it opens an Excel file.
    (profile / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
        '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
        '</oor:items>\n')
    subprocess.run(
        [str(LIBREOFFICE), f"-env:UserInstallation={(work_dir / 'profile').as_uri()}",
         "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(work_dir / "recalc"),
         str(HAND_CHECK_FILE)], check=True, capture_output=True, timeout=300)
    recalc = load_workbook(work_dir / "recalc" / HAND_CHECK_FILE.name, data_only=True)["Table"]

    worst, calls_match = 0.0, True
    print(f"{'s_1':<14}{'go':>9}{'fg':>9}{'punt':>9}{'f*':>9}  x*    | solver: go, fg, punt, best")
    for i, ((d, y, t), row) in enumerate(zip(states, solver_rows)):
        excel = [recalc.cell(row=2 + i, column=c).value for c in range(1, 7)]
        exact = F[(1, y, t)][:, d_vals == d].ravel()   # solver values before any rounding
        worst = max(worst, *np.abs(np.array(excel[1:4]) - exact))
        calls_match &= excel[5] == row["best"]
        print(f"{excel[0]:<14}{excel[1]:>9.4f}{excel[2]:>9.4f}{excel[3]:>9.4f}{excel[4]:>9.4f}  "
              f"{excel[5]:<5} | {exact[0]:.4f}, {exact[1]:.4f}, {exact[2]:.4f}, {row['best']}")
    print(f"Largest gap between Excel and the solver: {worst:.1e}. Best calls match: {calls_match}")
print(f"Workbook saved to: {HAND_CHECK_FILE}")

# ===============================================================
# Sanity checks
# ===============================================================
print("\n========== Sanity checks ==========")
failures = []

# 1. Down 3 with M = 1: a punt ends the game while behind, so it is worth 0.
m1_down3 = policy[(policy["M"] == 1) & (policy["d"] == -3)]
ok = (m1_down3["f_punt"] == 0).all()
print(f"1. Down 3, M = 1: punt = 0 in all {len(m1_down3)} states: {ok}")
failures += [] if ok else ["down 3 punt"]

# 2. Up 10 with M = 1: no way to lose, every call near 1.
m1_up10 = policy[(policy["M"] == 1) & (policy["d"] == 10)]
low = m1_up10[["f_go", "f_fg", "f_punt"]].min().min()
ok = low > 0.999
print(f"2. Up 10, M = 1: smallest win probability over every state and call = {low:.6f}: {ok}")
failures += [] if ok else ["up 10 near 1"]

# 3. 4th and 1 at the opponent's 2 (exact yardline), down 4, M = 1: go beats fg.
go2, fg2, _ = call_values(O[0], 2, 1)[:, d_vals == -4].ravel()
ok = go2 > fg2
print(f"3. 4th and 1 at the opponent's 2, down 4, M = 1: go {go2:.4f} vs fg {fg2:.4f}: {ok}")
failures += [] if ok else ["4th and 1 at the 2"]

# 4. Every win probability is between 0 and 1.
vals = policy[["f_go", "f_fg", "f_punt"]]
ok = bool(((vals >= 0) & (vals <= 1)).all().all())
print(f"4. Every win probability is between 0 and 1: {ok}")
failures += [] if ok else ["range"]

# 5. More points never hurts: each call's win probability rises (or stays) with d.
steps = policy.sort_values(["M", "y", "t", "d"]).groupby(["M", "y", "t"])[["f_go", "f_fg", "f_punt"]].diff()
ok = bool((steps.fillna(0) >= -1e-9).all().all())
print(f"5. Win probability never drops as d goes up: {ok}")
failures += [] if ok else ["monotone in d"]

print(f"\nFailures: {failures if failures else 'none'}")
print(f"Policy saved to: {RESULTS_DIR / 'policy.csv'}")
