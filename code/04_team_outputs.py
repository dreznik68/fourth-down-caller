"""
04_team_outputs.py

What this script does:
    Builds outputs/Week1_Data_Summary.xlsx, the Excel workbook our teammates
    work from. It has:
        - summary tabs, where every number is a live Excel formula that reads
          from the raw data tabs (nothing is pasted in)
        - raw data tabs with the cleaned data from scripts 02 and 03
    Then it checks the workbook:
        1. No play appears twice.
        2. LibreOffice recalculates every formula, and each result is compared
           with the same number computed here in pandas. Any mismatch is printed.

How to run (from the project root folder):
    python3 code/04_team_outputs.py

Needs:
    data/fourth_down_attempts.csv, data/field_goals.csv, data/punts.csv,
    data/drives.csv (run scripts 01, 02, and 03 first)
    LibreOffice in /Applications (only for the recalculation check; the
    workbook is still built without it)
"""

import math
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.formula import ArrayFormula

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "Week1_Data_Summary.xlsx"
LIBREOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")

BUCKET_SIZE = 5        # yards per bucket (same as 02_filter_plays.py)
MIN_START_BUCKET = 35  # punts from yardline_100 39 or less share one start bucket

# Punt flags that mean "leave this punt out of the distribution" (see 02_filter_plays.py).
PUNT_EXCLUDE_FLAGS = ["has_penalty", "is_muffed_recovered", "is_fumble_recovered",
                      "return_team_scored", "punting_team_scored"]

# Formatting
FONT = Font(name="Arial", size=11)
BOLD = Font(name="Arial", size=11, bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
PCT = "0.0%"
YARDS = "0.0"
COUNT = "#,##0"
# Excel measures column width in characters of its default font (Calibri).
# Arial is wider, so widths are stretched by this much to fit the text.
ARIAL_WIDTH = 1.15

OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------
# Step 1: Load the cleaned data and check for double counting
# ---------------------------------------------------------------
go = pd.read_csv(DATA_DIR / "fourth_down_attempts.csv")
fg = pd.read_csv(DATA_DIR / "field_goals.csv")
punts = pd.read_csv(DATA_DIR / "punts.csv")
drives = pd.read_csv(DATA_DIR / "drives.csv")

print("Double counting check (each play or drive should appear exactly once):")
for name, df, key in [("fourth_down_attempts", go, ["game_id", "play_id"]),
                      ("field_goals", fg, ["game_id", "play_id"]),
                      ("punts", punts, ["game_id", "play_id"]),
                      ("drives", drives, ["game_id", "fixed_drive"])]:
    dupes = int(df.duplicated(subset=key).sum())
    print(f"  {name}: {len(df):,} rows, {dupes} repeated")
    if dupes:
        raise ValueError(f"{name} has repeated rows. Stopping.")
all_plays = pd.concat([go[["game_id", "play_id"]], fg[["game_id", "play_id"]],
                       punts[["game_id", "play_id"]]])
in_two_tabs = int(all_plays.duplicated().sum())
print(f"  plays that appear in more than one play file: {in_two_tabs}")
if in_two_tabs:
    raise ValueError("Some plays appear in more than one file. Stopping.")

# Drives must be grouped by game for the "Games" formula on the Drive Results tab.
if (drives["game_id"] != drives["game_id"].shift()).sum() != drives["game_id"].nunique():
    raise ValueError("drives.csv is not grouped by game_id. Stopping.")

# Which punts the distribution uses (same rule as 02_filter_plays.py).
punts["used_in_distribution"] = (punts[PUNT_EXCLUDE_FLAGS].sum(axis=1) == 0).astype(int)


# ---------------------------------------------------------------
# Helpers for writing cells
# ---------------------------------------------------------------
# Every formula cell we write is also computed in pandas and stored here, so we
# can compare after LibreOffice recalculates: (tab, cell, description, expected value)
checks = []


def put(ws, ref, value, font=FONT, fmt=None, expected=None, label=None, wrap=False):
    """Write one cell. If expected is given, remember it for the check."""
    cell = ws[ref]
    cell.value = value
    cell.font = font
    if fmt:
        cell.number_format = fmt
    if wrap:
        cell.alignment = WRAP
    if expected is not None:
        checks.append((ws.title, ref, label or ref, float(expected)))


def put_array(ws, ref, formula, fmt=None, expected=None, label=None):
    """Write an array formula (Excel shows it with { } around it)."""
    put(ws, ref, ArrayFormula(ref, formula), fmt=fmt, expected=expected, label=label)


def headers(ws, row, col, names):
    """Write bold header names across a row, starting at column number col."""
    for i, name in enumerate(names):
        put(ws, f"{get_column_letter(col + i)}{row}", name, font=BOLD)


def fit_columns(ws, skip=(), min_width=8, max_width=60):
    """Set each column's width to fit its longest text. Formula cells count as 12
    characters. Cells listed in skip (long titles and notes) are ignored."""
    widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None or cell.coordinate in skip:
                continue
            if isinstance(cell.value, ArrayFormula) or str(cell.value).startswith("="):
                length = 12
            else:
                length = len(str(cell.value)) + (2 if cell.font.bold else 0)
            widths[cell.column_letter] = max(widths.get(cell.column_letter, 0), length)
    for letter, length in widths.items():
        ws.column_dimensions[letter].width = min(max(length * ARIAL_WIDTH + 2, min_width), max_width)


def fit_wrapped_rows(ws, col_letter, first_row, last_row):
    """Make rows tall enough for wrapped text in one column (Excel does not
    always do this by itself when it opens the file)."""
    chars_per_line = ws.column_dimensions[col_letter].width / ARIAL_WIDTH
    for r in range(first_row, last_row + 1):
        text = ws[f"{col_letter}{r}"].value
        if isinstance(text, str):
            lines = math.ceil(len(text) / chars_per_line)
            if lines > 1:
                ws.row_dimensions[r].height = 15 * lines


def bucket_start(value):
    """Round down to the start of a 5-yard bucket: 43 -> 40, -3 -> -5."""
    return int(math.floor(value / BUCKET_SIZE) * BUCKET_SIZE)


def style_line_chart(chart, title, x_title, y_title, y_format):
    chart.title = title
    chart.x_axis.title = x_title
    chart.y_axis.title = y_title
    chart.y_axis.number_format = y_format
    chart.legend = None
    chart.x_axis.delete = False  # without these two lines, new Excel versions hide the axes
    chart.y_axis.delete = False
    chart.height, chart.width = 9, 17
    chart.series[0].marker.symbol = "circle"
    chart.series[0].smooth = False  # straight lines between points, so the chart does not invent a curve
    return chart


wb = Workbook()
wb.calculation = CalcProperties(fullCalcOnLoad=True)  # Excel recalculates when the file opens

# Create the tabs in the order teammates should see them. The raw tabs are
# filled first, because the summary formulas need to know their cell ranges.
tab_names = ["How To Use", "Column Guide", "Conversion by Yards", "FG by Distance",
             "Punt Distance", "Drive Results", "Raw_4thDown", "Raw_FG", "Raw_Punts", "Raw_Drives"]
wb.active.title = tab_names[0]
for name in tab_names[1:]:
    wb.create_sheet(name)

# ---------------------------------------------------------------
# Step 2: Raw data tabs
# ---------------------------------------------------------------
# The raw tabs hold the columns from the task list plus the flag columns and
# desc. play_id is only used for the double counting check, so it is left out.
raw_tables = {
    "Raw_4thDown": go.drop(columns=["play_id"]),
    "Raw_FG": fg.drop(columns=["play_id"]),
    "Raw_Punts": punts.drop(columns=["play_id"]),
    "Raw_Drives": drives,
}
# Put used_in_distribution right before desc in Raw_Punts.
punt_cols = [c for c in raw_tables["Raw_Punts"].columns if c not in ("used_in_distribution", "desc")]
raw_tables["Raw_Punts"] = raw_tables["Raw_Punts"][punt_cols + ["used_in_distribution", "desc"]]

# R["Raw_Punts"]["net_punt_yards"] -> "Raw_Punts!$L$2:$L$16795" (used in formulas)
R = {}

for tab, df in raw_tables.items():
    ws = wb[tab]
    df = df.copy()
    # Columns read from CSV as decimals because of blanks (like first_4th_ydstogo)
    # are stored as whole numbers when every value is whole.
    for col in df.columns:
        if df[col].dtype == float and (df[col].dropna() % 1 == 0).all():
            df[col] = df[col].astype("Int64")
    letters = {col: get_column_letter(i + 1) for i, col in enumerate(df.columns)}
    last_row = len(df) + 1
    R[tab] = {col: f"{tab}!${letter}$2:${letter}${last_row}" for col, letter in letters.items()}

    rows = df.astype(object).where(df.notna(), None).values.tolist()

    if tab == "Raw_Punts":
        # used_in_distribution is a live formula: 1 if all five "left out" flags are 0.
        first, last = letters[PUNT_EXCLUDE_FLAGS[0]], letters[PUNT_EXCLUDE_FLAGS[-1]]
        flag_positions = [list(df.columns).index(f) for f in PUNT_EXCLUDE_FLAGS]
        if flag_positions != list(range(flag_positions[0], flag_positions[0] + len(flag_positions))):
            raise ValueError("The punt exclusion flag columns are not next to each other. Stopping.")
        used_index = list(df.columns).index("used_in_distribution")
        for i, row in enumerate(rows):
            r = i + 2
            row[used_index] = f"=IF(SUM({first}{r}:{last}{r})=0,1,0)"

    ws.append(list(df.columns))
    for row in rows:
        ws.append(row)

    for cell in ws[1]:
        cell.font = BOLD
    decimal_cols = {letters[c] for c in ("wp",) if c in letters}
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = FONT
            if cell.column_letter in decimal_cols:
                cell.number_format = "0.000"

    # Column widths: fit the longest value, but keep desc to a readable width.
    for col, letter in letters.items():
        longest = max(len(col), int(df[col].astype(str).str.len().max())) * ARIAL_WIDTH + 2
        ws.column_dimensions[letter].width = min(longest, 100 if col == "desc" else 40)

# Check every used_in_distribution formula against pandas (sum of the column).
checks.append(("Raw_Punts", "used_in_distribution", "Raw_Punts used_in_distribution (all rows)",
               float(punts["used_in_distribution"].sum())))

# ---------------------------------------------------------------
# Step 3: Conversion by Yards
# ---------------------------------------------------------------
ws = wb["Conversion by Yards"]
r4 = R["Raw_4thDown"]
est = go[(go["is_fake_kick"] == 0) & (go["is_botched_snap"] == 0)]
not_fake = f"{r4['is_fake_kick']},0,{r4['is_botched_snap']},0"

headers(ws, 1, 1, ["Yards to go", "Attempts", "Conversions", "Conversion rate"])
yard_rows = list(range(1, 10)) + ["10+"]
for i, ytg in enumerate(yard_rows):
    r = i + 2
    if ytg == "10+":
        criteria, mask = '">=10"', est["ydstogo"] >= 10
    else:
        criteria, mask = f"A{r}", est["ydstogo"] == ytg
    attempts = int(mask.sum())
    conversions = int(est.loc[mask, "fourth_down_converted"].sum())
    put(ws, f"A{r}", ytg)
    put(ws, f"B{r}", f"=COUNTIFS({r4['ydstogo']},{criteria},{not_fake})", fmt=COUNT,
        expected=attempts, label=f"Attempts, {ytg} to go")
    put(ws, f"C{r}", f"=COUNTIFS({r4['ydstogo']},{criteria},{not_fake},"
                     f"{r4['fourth_down_converted']},1)", fmt=COUNT,
        expected=conversions, label=f"Conversions, {ytg} to go")
    put(ws, f"D{r}", f"=C{r}/B{r}", fmt=PCT, expected=conversions / attempts,
        label=f"Conversion rate, {ytg} to go")
total_row = len(yard_rows) + 2
put(ws, f"A{total_row}", "All", font=BOLD)
put(ws, f"B{total_row}", f"=SUM(B2:B{total_row - 1})", font=BOLD, fmt=COUNT,
    expected=len(est), label="Attempts, all")
put(ws, f"C{total_row}", f"=SUM(C2:C{total_row - 1})", font=BOLD, fmt=COUNT,
    expected=est["fourth_down_converted"].sum(), label="Conversions, all")
put(ws, f"D{total_row}", f"=C{total_row}/B{total_row}", font=BOLD, fmt=PCT,
    expected=est["fourth_down_converted"].mean(), label="Conversion rate, all")

n = total_row + 2
put(ws, f"A{n}", "Fake punts, fake field goals, and botched snaps are left out.")
put(ws, f"A{n + 1}", "Only rows with is_fake_kick = 0 and is_botched_snap = 0 are counted.")
put(ws, f"A{n + 2}", "Plays left out")
put(ws, f"B{n + 2}", f"=COUNTA({r4['game_id']})-B{total_row}", fmt=COUNT,
    expected=len(go) - len(est), label="Plays left out")
put(ws, f"A{n + 3}", "Conversion rate if every play were counted")
put(ws, f"B{n + 3}", f"=AVERAGE({r4['fourth_down_converted']})", fmt=PCT,
    expected=go["fourth_down_converted"].mean(), label="Conversion rate, every play")
fit_columns(ws, skip={f"A{n}", f"A{n + 1}"})

chart = LineChart()
chart.add_data(Reference(ws, min_col=4, min_row=1, max_row=total_row - 1), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=total_row - 1))
style_line_chart(chart, "Fourth-down conversion rate by yards to go",
                 "Yards to go", "Conversion rate", "0%")
chart.y_axis.scaling.min, chart.y_axis.scaling.max = 0, 1
ws.add_chart(chart, "F2")

# ---------------------------------------------------------------
# Step 4: FG by Distance
# ---------------------------------------------------------------
ws = wb["FG by Distance"]
rf = R["Raw_FG"]
headers(ws, 1, 1, ["Kick distance (yards)", "From", "To", "Attempts", "Makes", "Make rate"])
fg_bins = range(bucket_start(fg["kick_distance"].min()), bucket_start(fg["kick_distance"].max()) + 1,
                BUCKET_SIZE)
for i, lo in enumerate(fg_bins):
    r = i + 2
    hi = lo + BUCKET_SIZE - 1
    mask = fg["kick_distance"].between(lo, hi)
    attempts, makes = int(mask.sum()), int(fg.loc[mask, "made"].sum())
    in_bin = f'{rf["kick_distance"]},">="&B{r},{rf["kick_distance"]},"<="&C{r}'
    put(ws, f"A{r}", f"{lo}-{hi}")
    put(ws, f"B{r}", lo)
    put(ws, f"C{r}", hi)
    put(ws, f"D{r}", f"=COUNTIFS({in_bin})", fmt=COUNT, expected=attempts, label=f"FG attempts {lo}-{hi}")
    put(ws, f"E{r}", f"=COUNTIFS({in_bin},{rf['made']},1)", fmt=COUNT, expected=makes,
        label=f"FG makes {lo}-{hi}")
    put(ws, f"F{r}", f"=E{r}/D{r}", fmt=PCT, expected=makes / attempts, label=f"FG make rate {lo}-{hi}")
total_row = len(fg_bins) + 2
put(ws, f"A{total_row}", "All", font=BOLD)
put(ws, f"D{total_row}", f"=SUM(D2:D{total_row - 1})", font=BOLD, fmt=COUNT,
    expected=len(fg), label="FG attempts, all")
put(ws, f"E{total_row}", f"=SUM(E2:E{total_row - 1})", font=BOLD, fmt=COUNT,
    expected=fg["made"].sum(), label="FG makes, all")
put(ws, f"F{total_row}", f"=E{total_row}/D{total_row}", font=BOLD, fmt=PCT,
    expected=fg["made"].mean(), label="FG make rate, all")

n = total_row + 2
put(ws, f"A{n}", "All field goal attempts are counted, including kicks not on 4th down,")
put(ws, f"A{n + 1}", "because the kick itself does not depend on the down.")
put(ws, f"A{n + 2}", "Kicks not on 4th down (included above)")
put(ws, f"D{n + 2}", f"=COUNTIFS({rf['on_fourth_down']},0)", fmt=COUNT,
    expected=(fg["on_fourth_down"] == 0).sum(), label="FG kicks not on 4th down")
put(ws, f"A{n + 3}", "Make rate using 4th-down kicks only, for comparison")
put(ws, f"F{n + 3}", f"=AVERAGEIFS({rf['made']},{rf['on_fourth_down']},1)", fmt=PCT,
    expected=fg.loc[fg["on_fourth_down"] == 1, "made"].mean(), label="FG make rate, 4th down only")
fit_columns(ws, skip={f"A{n}", f"A{n + 1}", f"A{n + 2}", f"A{n + 3}"})

chart = LineChart()
chart.add_data(Reference(ws, min_col=6, min_row=1, max_row=total_row - 1), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=total_row - 1))
style_line_chart(chart, "Field goal make rate by kick distance",
                 "Kick distance (yards)", "Make rate", "0%")
chart.y_axis.scaling.min, chart.y_axis.scaling.max = 0, 1
ws.add_chart(chart, "H2")

# ---------------------------------------------------------------
# Step 5: Punt Distance
# ---------------------------------------------------------------
ws = wb["Punt Distance"]
rp = R["Raw_Punts"]
used = punts[punts["used_in_distribution"] == 1]
net, yl, use = rp["net_punt_yards"], rp["yardline_100"], rp["used_in_distribution"]
skip = set()

# 5a) Summary statistics of net punt yards (punts used in the distribution only)
headers(ws, 1, 1, ["Statistic", "Value"])
stats = [
    ("Punts used (used_in_distribution = 1)", f"=COUNTIFS({use},1)", None, len(used), COUNT),
    ("Mean net punt yards", f"=AVERAGEIFS({net},{use},1)", None, used["net_punt_yards"].mean(), YARDS),
    ("Standard deviation", None, f"=_xlfn.STDEV.S(IF({use}=1,{net}))", used["net_punt_yards"].std(), YARDS),
    ("Min", None, f"=MIN(IF({use}=1,{net}))", used["net_punt_yards"].min(), YARDS),
    ("Max", None, f"=MAX(IF({use}=1,{net}))", used["net_punt_yards"].max(), YARDS),
    ("Median", None, f"=MEDIAN(IF({use}=1,{net}))", used["net_punt_yards"].median(), YARDS),
]
for i, (label, formula, array_formula, expected, fmt) in enumerate(stats):
    r = i + 2
    put(ws, f"A{r}", label)
    if formula:
        put(ws, f"B{r}", formula, fmt=fmt, expected=expected, label=f"Punts: {label}")
    else:
        put_array(ws, f"B{r}", array_formula, fmt=fmt, expected=expected, label=f"Punts: {label}")
put(ws, "A8", "Punts left out (see Column Guide)")
put(ws, "B8", f"=COUNTA({rp['game_id']})-B2", fmt=COUNT,
    expected=len(punts) - len(used), label="Punts: left out")

# 5b) Histogram table: punts in each 5-yard net yards bin
net_bins = list(range(bucket_start(used["net_punt_yards"].min()),
                      bucket_start(used["net_punt_yards"].max()) + 1, BUCKET_SIZE))
put(ws, "A10", "Histogram of net punt yards (5-yard bins)", font=BOLD)
skip.add("A10")
headers(ws, 11, 1, ["Net yards bin", "From", "To", "Punts", "Share of punts"])
hist_first = 12
for i, lo in enumerate(net_bins):
    r = hist_first + i
    hi = lo + BUCKET_SIZE - 1
    count = int(used["net_punt_yards"].between(lo, hi).sum())
    put(ws, f"A{r}", f"{lo} to {hi}")
    put(ws, f"B{r}", lo)
    put(ws, f"C{r}", hi)
    put(ws, f"D{r}", f'=COUNTIFS({net},">="&B{r},{net},"<="&C{r},{use},1)', fmt=COUNT,
        expected=count, label=f"Punt histogram {lo} to {hi}")
    put(ws, f"E{r}", f"=D{r}/$B$2", fmt=PCT, expected=count / len(used),
        label=f"Punt histogram share {lo} to {hi}")
hist_last = hist_first + len(net_bins) - 1
put(ws, f"A{hist_last + 1}", "All", font=BOLD)
put(ws, f"D{hist_last + 1}", f"=SUM(D{hist_first}:D{hist_last})", font=BOLD, fmt=COUNT,
    expected=len(used), label="Punt histogram total")
put(ws, f"E{hist_last + 1}", f"=SUM(E{hist_first}:E{hist_last})", font=BOLD, fmt=PCT,
    expected=1.0, label="Punt histogram share total")

chart = BarChart()
chart.type = "col"
chart.gapWidth = 10
chart.add_data(Reference(ws, min_col=4, min_row=11, max_row=hist_last), titles_from_data=True)
# Label each bar with the low end of its bin (the From column), so labels stay short.
chart.set_categories(Reference(ws, min_col=2, min_row=hist_first, max_row=hist_last))
chart.title = "Net punt yards (punts used in the distribution)"
chart.x_axis.title = "Net punt yards (each bar is a 5-yard bin, labeled by its low end)"
chart.y_axis.title = "Number of punts"
chart.y_axis.number_format = "#,##0"
chart.legend = None
chart.x_axis.delete = False
chart.y_axis.delete = False
chart.height, chart.width = 10, 20
ws.add_chart(chart, "H10")

# 5c) Mean and SD of net punt yards by starting field position
start_bins = list(range(MIN_START_BUCKET, bucket_start(punts["yardline_100"].max()) + 1, BUCKET_SIZE))
t = hist_last + 4
put(ws, f"A{t}", "Net punt yards by starting field position (yardline_100 where the punt started)",
    font=BOLD)
skip.add(f"A{t}")
headers(ws, t + 1, 1, ["Start bucket", "From", "To", "Punts", "Mean net yards", "SD net yards"])
sb_first = t + 2
start_ranges = []  # (label, from, to) for each start bucket
for i, lo in enumerate(start_bins):
    r = sb_first + i
    from_yl = 1 if lo == MIN_START_BUCKET else lo
    hi = lo + BUCKET_SIZE - 1
    label = f"{hi} or less" if lo == MIN_START_BUCKET else f"{lo}-{hi}"
    start_ranges.append((label, from_yl, hi))
    in_start = used["yardline_100"].between(from_yl, hi)
    values = used.loc[in_start, "net_punt_yards"]
    in_bucket = f'{yl},">="&B{r},{yl},"<="&C{r},{use},1'
    put(ws, f"A{r}", label)
    put(ws, f"B{r}", from_yl)
    put(ws, f"C{r}", hi)
    put(ws, f"D{r}", f"=COUNTIFS({in_bucket})", fmt=COUNT, expected=len(values),
        label=f"Punts from start {label}")
    put(ws, f"E{r}", f"=AVERAGEIFS({net},{in_bucket})", fmt=YARDS, expected=values.mean(),
        label=f"Mean net yards, start {label}")
    put_array(ws, f"F{r}", f"=_xlfn.STDEV.S(IF(({use}=1)*({yl}>=B{r})*({yl}<=C{r}),{net}))",
              fmt=YARDS, expected=values.std(), label=f"SD net yards, start {label}")
sb_last = sb_first + len(start_bins) - 1
put(ws, f"A{sb_last + 1}", "All", font=BOLD)
put(ws, f"D{sb_last + 1}", f"=SUM(D{sb_first}:D{sb_last})", font=BOLD, fmt=COUNT,
    expected=len(used), label="Punts by start bucket, total")

# 5d) Full distribution: share of punts from each start bucket in each net yards bin
t = sb_last + 4
put(ws, f"A{t}", "Distribution of net punt yards by start bucket: the share of punts from each "
                 "start bucket (columns) that landed in each net yards bin (rows). "
                 "Each column adds up to 100%.", font=BOLD)
skip.add(f"A{t}")
head = t + 1
headers(ws, head, 1, ["Net yards bin", "From", "To"])
put(ws, f"A{head + 1}", "Start from (yardline_100)", font=BOLD)
put(ws, f"A{head + 2}", "Start to (yardline_100)", font=BOLD)
put(ws, f"A{head + 3}", "Punts from this start bucket", font=BOLD)
m_first = head + 4
for j, (label, from_yl, hi) in enumerate(start_ranges):
    c = get_column_letter(4 + j)
    in_start = used["yardline_100"].between(from_yl, hi)
    n_start = int(in_start.sum())
    put(ws, f"{c}{head}", label, font=BOLD)
    put(ws, f"{c}{head + 1}", from_yl)
    put(ws, f"{c}{head + 2}", hi)
    put(ws, f"{c}{head + 3}", f'=COUNTIFS({yl},">="&{c}${head + 1},{yl},"<="&{c}${head + 2},{use},1)',
        fmt=COUNT, expected=n_start, label=f"Matrix punts, start {label}")
    for i, lo in enumerate(net_bins):
        r = m_first + i
        if j == 0:
            put(ws, f"A{r}", f"{lo} to {lo + BUCKET_SIZE - 1}")
            put(ws, f"B{r}", lo)
            put(ws, f"C{r}", lo + BUCKET_SIZE - 1)
        count = int((in_start & used["net_punt_yards"].between(lo, lo + BUCKET_SIZE - 1)).sum())
        put(ws, f"{c}{r}",
            f'=COUNTIFS({net},">="&$B{r},{net},"<="&$C{r},'
            f'{yl},">="&{c}${head + 1},{yl},"<="&{c}${head + 2},{use},1)/{c}${head + 3}',
            fmt=PCT, expected=count / n_start, label=f"Matrix share, start {label}, net {lo}")
    m_last = m_first + len(net_bins) - 1
    put(ws, f"{c}{m_last + 1}", f"=SUM({c}{m_first}:{c}{m_last})", font=BOLD, fmt=PCT,
        expected=1.0, label=f"Matrix column total, start {label}")
put(ws, f"A{m_last + 1}", "Total (should be 100%)", font=BOLD)
fit_columns(ws, skip=skip)
ws.column_dimensions["A"].width = 38

# ---------------------------------------------------------------
# Step 6: Drive Results
# ---------------------------------------------------------------
ws = wb["Drive Results"]
rd = R["Raw_Drives"]
headers(ws, 1, 1, ["Drive result", "Drives", "Share of drives"])
results = drives["drive_result"].value_counts()
for i, (result, count) in enumerate(results.items()):
    r = i + 2
    put(ws, f"A{r}", result)
    put(ws, f"B{r}", f"=COUNTIFS({rd['drive_result']},A{r})", fmt=COUNT, expected=count,
        label=f"Drives: {result}")
    put(ws, f"C{r}", f"=B{r}/$B${len(results) + 2}", fmt=PCT, expected=count / len(drives),
        label=f"Share: {result}")
total_row = len(results) + 2
put(ws, f"A{total_row}", "All drives", font=BOLD)
put(ws, f"B{total_row}", f"=COUNTA({rd['game_id']})", font=BOLD, fmt=COUNT,
    expected=len(drives), label="Drives: all")
put(ws, f"C{total_row}", f"=SUM(C2:C{total_row - 1})", font=BOLD, fmt=PCT,
    expected=1.0, label="Share: all")

n = total_row + 2
headers(ws, n, 1, ["Measure", "Value", "Share"])
last = len(drives) + 1
games_formula = (f"=SUMPRODUCT(--(Raw_Drives!$A$3:$A${last}<>Raw_Drives!$A$2:$A${last - 1}))+1")
put(ws, f"A{n + 1}", "Games")
put(ws, f"B{n + 1}", games_formula, fmt=COUNT, expected=drives["game_id"].nunique(), label="Games")
put(ws, f"A{n + 2}", "Average drives per team per game")
put(ws, f"B{n + 2}", f"=B{total_row}/(2*B{n + 1})", fmt="0.00",
    expected=len(drives) / (2 * drives["game_id"].nunique()), label="Average drives per team per game")
reached = int((drives["reached_fourth_down"] == 1).sum())
two_plus = int((drives["num_fourth_downs"] >= 2).sum())
put(ws, f"A{n + 3}", "Drives that reached fourth down")
put(ws, f"B{n + 3}", f"=COUNTIFS({rd['reached_fourth_down']},1)", fmt=COUNT, expected=reached,
    label="Drives that reached 4th down")
put(ws, f"C{n + 3}", f"=B{n + 3}/B{total_row}", fmt=PCT, expected=reached / len(drives),
    label="Share that reached 4th down")
put(ws, f"A{n + 4}", "Drives with 2 or more fourth downs")
put(ws, f"B{n + 4}", f'=COUNTIFS({rd["num_fourth_downs"]},">=2")', fmt=COUNT, expected=two_plus,
    label="Drives with 2+ fourth downs")
put(ws, f"C{n + 4}", f"=B{n + 4}/B{total_row}", fmt=PCT, expected=two_plus / len(drives),
    label="Share with 2+ fourth downs (all drives)")
put(ws, f"A{n + 5}", "Of drives that reached fourth down, share with 2 or more")
put(ws, f"C{n + 5}", f"=B{n + 4}/B{n + 3}", fmt=PCT, expected=two_plus / reached,
    label="Share with 2+ fourth downs (drives that reached 4th)")
put(ws, f"A{n + 7}", "Games counts how many times game_id changes going down Raw_Drives "
                     "(the rows are grouped by game).")
put(ws, f"A{n + 8}", "Fourth downs wiped out by a penalty are not counted.")
fit_columns(ws, skip={f"A{n + 7}", f"A{n + 8}"})

# ---------------------------------------------------------------
# Step 7: Column Guide
# ---------------------------------------------------------------
GUIDE = {
    "game_id": "Game ID: season_week_away_home. For example, 2023_01_DET_KC is Week 1 of 2023, Detroit at Kansas City.",
    "season": "NFL season (2018 to 2025). January games count in the season that started the September before.",
    "posteam": "Team with the ball: the offense (the kicking team on field goals and punts). Teams use today's abbreviations, so the Raiders are LV in every season even though game_id says OAK for 2018 and 2019.",
    "defteam": "Team on defense (the receiving team on punts). Uses today's team abbreviations, like posteam.",
    "qtr": "Quarter (1 to 4; 5 means overtime).",
    "game_seconds_remaining": "Seconds left in regulation when the play started (3600 = kickoff, 0 = end of the 4th quarter). In overtime it counts down the overtime period.",
    "yardline_100": "Yards from the opponent's end zone, so 1 means the opponent's 1-yard line and 99 means your own 1.",
    "ydstogo": "Yards needed for a first down (or to the goal line when it is goal to go).",
    "score_differential": "Offense's score minus the defense's score when the play started (positive = offense ahead).",
    "wp": "nflfastR's estimated chance that the offense wins the game, before the play (0 to 1).",
    "fourth_down_converted": "1 if the offense got a first down or a touchdown, 0 if not.",
    "fourth_down_failed": "1 if the offense did not get a first down (turnover on downs or a turnover), 0 if not.",
    "is_fake_kick": "1 if the play was run from punt or field goal formation (a fake). Left out of conversion rates.",
    "is_botched_snap": "1 if nflfastR marked the play as aborted (a bad snap or a bad exchange). Left out of conversion rates.",
    "desc": "nflfastR's text description of the play, so you can read what happened.",
    "field_goal_result": "made, missed, or blocked.",
    "made": "1 if the kick was good, 0 if it was missed or blocked.",
    "on_fourth_down": "1 if the kick was on 4th down. All kicks are used for make rates, because the kick does not depend on the down.",
    "return_yards": "Yards the returner gained (0 for fair catches, downed punts, and punts out of bounds).",
    "touchback": "1 if the punt was a touchback (the receiving team starts at its own 20).",
    "punt_blocked": "1 if the punt was blocked (from nflfastR).",
    "net_punt_yards": "How far the ball moved toward the receiving team's end zone. See \"How net_punt_yards was calculated\" below.",
    "is_blocked": "1 if the punt was blocked (same as punt_blocked). Blocked punts are KEPT in the punt distribution, because a block is a real outcome of choosing to punt.",
    "has_penalty": "1 if a penalty was called on the punt. Left out of the punt distribution, because penalty yards move the ball.",
    "is_muffed_recovered": "1 if the returner muffed the punt and the punting team got the ball back. Left out of the punt distribution.",
    "is_fumble_recovered": "1 if the returner caught the punt, then fumbled, and the punting team recovered. Left out of the punt distribution.",
    "return_team_scored": "1 if the receiving team scored on the play (punt return touchdown, blocked punt touchdown, or safety). Left out of the punt distribution.",
    "punting_team_scored": "1 if the punting team scored on the play (touchdown after a muff or fumble, or a safety). Left out of the punt distribution.",
    "used_in_distribution": "Formula: 1 if all five \"left out\" flags (has_penalty through punting_team_scored) are 0. The Punt Distance tab only uses rows where this is 1.",
    "fixed_drive": "Drive number within the game (nflfastR's fixed_drive).",
    "start_yardline_100": "yardline_100 on the drive's first snap (not the kickoff).",
    "start_game_seconds_remaining": "Seconds left in the game at the drive's first snap.",
    "start_qtr": "Quarter at the drive's first snap.",
    "start_score_differential": "Offense's score minus the defense's score at the drive's first snap.",
    "drive_result": "How the drive ended (nflfastR's fixed_drive_result). \"Opp touchdown\" means the defense scored, for example on an interception return.",
    "points_scored": "Points the offense scored on the drive, including the extra point or two-point try.",
    "reached_fourth_down": "1 if the drive had at least one fourth-down play that counted (plays wiped out by a penalty do not count).",
    "first_4th_yardline_100": "yardline_100 at the drive's first fourth-down play. Blank if the drive never reached fourth down.",
    "first_4th_ydstogo": "Yards to go at the drive's first fourth-down play. Blank if the drive never reached fourth down.",
    "num_fourth_downs": "Number of fourth-down plays on the drive that counted.",
}
GUIDE_BY_TAB = {
    ("Raw_FG", "kick_distance"): "Length of the kick in yards (about yardline_100 + 18: 10 yards of end zone plus about 8 yards back to the hold).",
    ("Raw_Punts", "kick_distance"): "Yards from the line of scrimmage to where the punt was caught, downed, or went out of bounds (only to the goal line on a touchback, and 0 on blocked punts).",
}

ws = wb["Column Guide"]
headers(ws, 1, 1, ["Tab", "Column", "Meaning"])
r = 2
for tab in ["Raw_4thDown", "Raw_FG", "Raw_Punts", "Raw_Drives"]:
    for col in raw_tables[tab].columns:
        meaning = GUIDE_BY_TAB.get((tab, col), GUIDE.get(col))
        if meaning is None:
            raise KeyError(f"No Column Guide entry for {tab} {col}. Add one to GUIDE.")
        put(ws, f"A{r}", tab, wrap=True)
        put(ws, f"B{r}", col, wrap=True)
        put(ws, f"C{r}", meaning, wrap=True)
        r += 1

r += 1
put(ws, f"A{r}", "How net_punt_yards was calculated", font=BOLD)
net_notes = [
    "net_punt_yards is how many yards the ball moved toward the receiving team's end zone, from where the punt started to where the play ended.",
    "Touchback: yardline_100 - 20, because the receiving team starts at its own 20. Example: a punt from the opponent's 45 goes into the end zone, so 45 - 20 = 25 yards.",
    "Blocked punt: nflfastR records 0 kick yards and 0 return yards, so we use where the ball ended up: the spot of the receiving team's next snap, or yardline_100 - 100 if the defense scored.",
    "Every other punt: kick_distance - return_yards. Example: a 50-yard punt returned 8 yards is 50 - 8 = 42 yards.",
    "Penalty yards are not counted. Punts with a penalty are flagged (has_penalty) and left out of the punt distribution.",
]
for note in net_notes:
    r += 1
    put(ws, f"C{r}", note, wrap=True)
fit_columns(ws, skip={f"A{r - len(net_notes)}"})
ws.column_dimensions["C"].width = 100
fit_wrapped_rows(ws, "C", 2, r)

# ---------------------------------------------------------------
# Step 8: How To Use
# ---------------------------------------------------------------
ws = wb["How To Use"]
put(ws, "A1", "Week 1 Data Summary: 4th Down Caller (IE 4520 Group 4)", font=BOLD)
ws.merge_cells("A3:C3")
put(ws, "A3", "This workbook has the cleaned NFL data for our fourth-down project and the summary "
              "numbers the model needs: how often teams convert on fourth down, how often field goals "
              "are good, how far punts go, and how drives end. Every number on the summary tabs is a "
              "live Excel formula that reads from the Raw tabs, so you can click any cell to see where "
              "it comes from. Plays left out of an estimate are marked with flag columns (1 = yes, "
              "0 = no), explained on the Column Guide tab.", wrap=True)
ws.row_dimensions[3].height = 66
put(ws, "A5", "Data source", font=BOLD)
put(ws, "B5", "nflfastR play-by-play, 2018 to 2025 NFL regular season (loaded with the nflreadpy Python package)")
put(ws, "A6", "Built on", font=BOLD)
put(ws, "B6", date.today().strftime("%B %-d, %Y"))
put(ws, "A7", "Built by", font=BOLD)
put(ws, "B7", "code/04_team_outputs.py (David reruns it when the data changes)")

headers(ws, 9, 1, ["Tab", "What it shows", "Mainly for"])
tab_guide = [
    ("How To Use", "This page: what the workbook is and what each tab shows.", "Everyone"),
    ("Column Guide", "What every column in the Raw tabs means, and how net punt yards was calculated.", "Everyone"),
    ("Conversion by Yards", "Fourth-down conversion rate for 1 to 9 and 10+ yards to go, with a line chart.", "Aidan (John for the probability trees)"),
    ("FG by Distance", "Field goal make rate by 5-yard kick distance, with a line chart.", "Aidan (John for the probability trees)"),
    ("Punt Distance", "Net punt yards: summary stats, a histogram, mean and SD by starting field position, and the full distribution by start bucket.", "Aidan (John for the probability trees)"),
    ("Drive Results", "How drives end, average drives per team per game, and how often a drive has 2 or more fourth downs.", "Charlie"),
    ("Raw_4thDown", "Every fourth-down run or pass (going for it), one row per play.", "Aidan"),
    ("Raw_FG", "Every field goal attempt, one row per kick.", "Aidan"),
    ("Raw_Punts", "Every punt, one row per punt.", "Aidan"),
    ("Raw_Drives", "Every drive, one row per drive.", "Charlie"),
]
for i, (tab, what, who) in enumerate(tab_guide):
    r = 10 + i
    put(ws, f"A{r}", tab, wrap=True)
    put(ws, f"B{r}", what, wrap=True)
    put(ws, f"C{r}", who, wrap=True)
fit_columns(ws, skip={"A1", "A3", "B5", "B7"})
ws.column_dimensions["B"].width = 80
fit_wrapped_rows(ws, "B", 10, 10 + len(tab_guide) - 1)

# Freeze the top row on every tab. Summary tabs print landscape, one page wide.
for ws in wb.worksheets:
    ws.freeze_panes = "A2"
    if not ws.title.startswith("Raw_"):
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

wb.save(OUTPUT_FILE)
size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
print(f"\nSaved {OUTPUT_FILE} ({size_mb:.1f} MB)")
for tab, df in raw_tables.items():
    print(f"  {tab}: {len(df):,} rows, {len(df.columns)} columns")

# ---------------------------------------------------------------
# Step 9: Recalculate with LibreOffice and compare with pandas
# ---------------------------------------------------------------
# LibreOffice opens a copy of the workbook, recalculates every formula, and
# saves the results. We read those results and compare each one with the
# number computed in pandas above.
if not LIBREOFFICE.exists():
    print("\nLibreOffice not found in /Applications, so the recalculation check was skipped.")
    raise SystemExit(0)

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
    '</oor:items>\n'
)
print("\nRecalculating with LibreOffice (this takes a minute)...")
subprocess.run(
    [str(LIBREOFFICE), f"-env:UserInstallation={(work_dir / 'profile').as_uri()}",
     "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(work_dir / "recalculated"),
     str(OUTPUT_FILE)],
    check=True, capture_output=True, timeout=900,
)
recalc = load_workbook(work_dir / "recalculated" / OUTPUT_FILE.name, data_only=True)

# Any formula error (like #VALUE! or #NAME?) anywhere on the summary tabs?
errors = []
for tab in tab_names[:6]:
    for row in recalc[tab].iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and (cell.value.startswith("#") or cell.value.startswith("Err:")):
                errors.append(f"{tab}!{cell.coordinate} = {cell.value}")

# used_in_distribution: compare every row with pandas.
used_col = get_column_letter(list(raw_tables["Raw_Punts"].columns).index("used_in_distribution") + 1)
excel_used = pd.to_numeric(
    pd.Series([recalc["Raw_Punts"][f"{used_col}{r}"].value for r in range(2, len(punts) + 2)]),
    errors="coerce").to_numpy()
used_row_mismatches = int((excel_used != punts["used_in_distribution"].values).sum())

mismatches = []
results_table = []
for tab, ref, label, expected in checks:
    if ref == "used_in_distribution":
        got = float(np.nansum(excel_used))
    else:
        got = recalc[tab][ref].value
    ok = isinstance(got, (int, float)) and math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-9)
    results_table.append((tab, ref, label, got, expected, ok))
    if not ok:
        mismatches.append((tab, ref, label, got, expected))

print("\n========== CHECKS: Excel formulas vs pandas ==========")
print(f"Formula cells checked: {len(checks):,}")
print(f"Matches: {len(checks) - len(mismatches):,}")
print(f"Mismatches: {len(mismatches)}")
for tab, ref, label, got, expected in mismatches:
    print(f"  MISMATCH {tab}!{ref} ({label}): Excel {got}, pandas {expected}")
print(f"Formula errors on summary tabs: {len(errors)}")
for e in errors[:20]:
    print(f"  {e}")
print(f"Raw_Punts used_in_distribution rows that differ from pandas: {used_row_mismatches}")

# Save the full side-by-side comparison next to the workbook, for reference.
pd.DataFrame(results_table, columns=["tab", "cell", "what", "excel_value", "pandas_value", "match"]).to_csv(
    work_dir / "formula_checks.csv", index=False)
shutil.copy(work_dir / "formula_checks.csv", DATA_DIR / "formula_checks.csv")
print(f"Full comparison saved to: {DATA_DIR / 'formula_checks.csv'}")
shutil.rmtree(work_dir)
