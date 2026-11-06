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

    The model itself (the recursion and the three calls) is in dp_model.py,
    so the sensitivity runs in 07_results.py use exactly the same code.

How to run (from the project root folder):
    python3 code/06_solve.py

Needs:
    data/inputs/ (run 05_inputs.py first)
    LibreOffice in /Applications (only for the hand check recalculation)

Field position:
    y in policy.csv is the 5-yard bucket name (40 means yardline_100 40 to 44).
    The formulas use the bucket's lowest yard as the exact yardline, so y = 40
    kicks from 57 yards. The yardline used is saved in the yardline column.
"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from dp_model import CALLS, IN_DIR, bi, call_values, load_inputs, policy_table, solve

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
RESULTS_DIR.mkdir(exist_ok=True)
HAND_CHECK_FILE = PROJECT_ROOT / "outputs" / "DP_Hand_Check.xlsx"
LIBREOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
M_MAX = 8  # possessions left: 1 to 8

# ===============================================================
# Solve and save policy.csv
# ===============================================================
inp = load_inputs()
d_vals, F, O = solve(inp, M_MAX)
policy = policy_table(d_vals, F)
policy.round(6).to_csv(RESULTS_DIR / "policy.csv", index=False)

print("========== policy.csv ==========")
print(f"Rows: {len(policy):,} = {M_MAX} values of M x {policy['d'].nunique()} values of d "
      f"x {len(F) // M_MAX} (y, t) states")
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
c_df = pd.read_csv(IN_DIR / "c_conversion.csv")
g_df = pd.read_csv(IN_DIR / "g_fieldgoal.csv").sort_values("kick_min")
d_df =pd.read_csv(IN_DIR / "D_drive.csv").set_index("start_bucket")
FONT, BOLD = Font(name="Arial", size=11), Font(name="Arial", size=11, bold=True)


def write_row(ws, row, values, bold=False, fmt=None):
    """Write a list of values (or formulas) across one row."""
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = BOLD if bold else FONT
        if fmt and isinstance(value, str) and value.startswith("="):
            cell.number_format = fmt


def boundary(x):
    """Excel formula for the boundary condition f*_2 at score difference x."""
    return f"=IF({x}>0,1,IF({x}=0,0.5,0))"


wb = Workbook()
inp_ws = wb.active
inp_ws.title = "Inputs"
write_row(inp_ws, 1, ["Inputs for the M = 1 hand check (counts from data/inputs, "
                      "probabilities are formulas)"], bold=True)

# c(t) for the t values used. Rows 3 to 6.
write_row(inp_ws, 3, ["t", "attempts", "conversions", "c(t)"], bold=True)
for i, t in enumerate(HC_T):
    r = c_df[c_df["t"] == t].iloc[0]
    write_row(inp_ws, 4 + i, [t, int(r["attempts"]), int(r["conversions"]), f"=C{4 + i}/B{4 + i}"],
              fmt="0.0000")
C_RANGE = "$A$4:$D$6"

# g(k): make rate by kick distance group (every group, shortest first).
G_ROW0 = 9
write_row(inp_ws, G_ROW0 - 1, ["kick from", "kick to", "attempts", "makes", "g(k)"], bold=True)
for i, r in enumerate(g_df.itertuples()):
    row = G_ROW0 + i
    write_row(inp_ws, row, [r.kick_min, r.kick_max, r.attempts, r.makes, f"=D{row}/C{row}"],
              fmt="0.0000")
G_LAST = G_ROW0 + len(g_df) - 1
G_RANGE = f"$A${G_ROW0}:$E${G_LAST}"

# D for the buckets of y - t that the states land in.
D_ROW0 = G_LAST + 3
d_buckets = sorted({bi(y - t) * 5 for _, y, t in states})
write_row(inp_ws, D_ROW0 - 1, ["D start bucket", "drives", "TD drives", "FG drives", "P_TD", "P_FG",
                               "P_none"], bold=True)
for i, b in enumerate(d_buckets):
    r, row = d_df.loc[b], D_ROW0 + i
    write_row(inp_ws, row, [b, int(r["drives"]), int(r["td_drives"]), int(r["fg_drives"]),
                            f"=C{row}/B{row}", f"=D{row}/B{row}", f"=1-E{row}-F{row}"], fmt="0.0000")
D_RANGE = f"$A${D_ROW0}:$G${D_ROW0 + len(d_buckets) - 1}"

# One row per state with every number its formulas use.
STATE_ROW0 = D_ROW0 + len(d_buckets) + 2
write_row(inp_ws, STATE_ROW0 - 1, ["state", "d", "y", "t", "c(t)", "y - t", "D bucket", "P_TD", "P_FG", "P_none",
                       "kick distance", "g(y + 17)", "f*_2(d + 7)", "f*_2(d + 3)", "f*_2(d)"], bold=True)
for i, (d, y, t) in enumerate(states):
    r = STATE_ROW0 + i
    write_row(inp_ws, r, [
        i + 1, d, y, t,
        f"=VLOOKUP(D{r},{C_RANGE},4,FALSE)",
        f"=C{r}-D{r}",
        f"=5*INT(F{r}/5)",
        f"=VLOOKUP(G{r},{D_RANGE},5,FALSE)",
        f"=VLOOKUP(G{r},{D_RANGE},6,FALSE)",
        f"=VLOOKUP(G{r},{D_RANGE},7,FALSE)",
        f"=C{r}+17",
        # The group whose "kick from" is the largest one at or below the kick
        # distance; 0 if the kick is longer than the longest make.
        f"=IF(K{r}>$B${G_LAST},0,VLOOKUP(K{r},{G_RANGE},5,TRUE))",
        boundary(f"B{r}+7"), boundary(f"B{r}+3"), boundary(f"B{r}"),
    ], fmt="0.0000")
note_row = STATE_ROW0 + len(states) + 1
write_row(inp_ws, note_row, ["f*_2 is the boundary condition: 1 if d > 0, 0.5 if d = 0, 0 if d < 0. "
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

for ws in (inp_ws, tab):
    ws.freeze_panes = "A2"
    for col in ws.columns:
        width = max(len(str(c.value)) if c.value is not None and not str(c.value).startswith("=")
                    else 8 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 18)
    ws.column_dimensions["A"].width = 18
HAND_CHECK_FILE.parent.mkdir(exist_ok=True)
wb.save(HAND_CHECK_FILE)

# ---------------------------------------------------------------
# Recalculate with LibreOffice and compare with the solver
# ---------------------------------------------------------------
print("\n========== Hand check (M = 1, d = -3) ==========")
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
    for i, (d, y, t) in enumerate(states):
        excel = [recalc.cell(row=2 + i, column=c).value for c in range(1, 7)]
        exact = F[(1, y, t)][:, d_vals == d].ravel()   # solver values before any rounding
        best = lookup(1, d, y, t)["best"]
        worst = max(worst, *np.abs(np.array(excel[1:4]) - exact))
        calls_match &= excel[5] == best
        print(f"{excel[0]:<14}{excel[1]:>9.4f}{excel[2]:>9.4f}{excel[3]:>9.4f}{excel[4]:>9.4f}  "
              f"{excel[5]:<5} | {exact[0]:.4f}, {exact[1]:.4f}, {exact[2]:.4f}, {best}")
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
go2, fg2, _ = call_values(inp, O[0], 2, 1)[:, d_vals == -4].ravel()
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
