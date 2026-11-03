"""
02_filter_plays.py

What this script does:
    Reads the regular season play-by-play file made by 01_pull_pbp.py and
    splits out the three kinds of fourth-down decisions we care about:
        a) go-for-it attempts  -> data/fourth_down_attempts.csv
        b) field goal attempts -> data/field_goals.csv
        c) punts               -> data/punts.csv
    It also saves a histogram of net punt yards -> data/net_punt_hist.png
    and prints checks (row counts and rates) for each file.

How to run (from the project root folder):
    python3 code/02_filter_plays.py

Needs:
    data/pbp_2018_2025.parquet (run 01_pull_pbp.py first)
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save the plot to a file instead of opening a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# ---------------------------------------------------------------
# File paths
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_FILE = DATA_DIR / "pbp_2018_2025.parquet"

# ---------------------------------------------------------------
# Columns we keep in each output file (from the task list)
# ---------------------------------------------------------------
FOURTH_DOWN_COLS = [
    "game_id", "season", "posteam", "defteam", "qtr", "game_seconds_remaining",
    "yardline_100", "ydstogo", "score_differential", "wp",
    "fourth_down_converted", "fourth_down_failed",
]
FIELD_GOAL_COLS = [
    "game_id", "season", "posteam", "qtr", "game_seconds_remaining",
    "yardline_100", "kick_distance", "field_goal_result", "score_differential", "wp",
]
PUNT_COLS = [
    "game_id", "season", "posteam", "qtr", "game_seconds_remaining",
    "yardline_100", "kick_distance", "return_yards", "touchback", "punt_blocked",
    "score_differential",
]

# Extra columns used only for filtering and checks (not saved to the CSVs).
#   down, play_type     -> to pick the plays
#   desc                -> the text description of the play, for spot checks
#   qb_kneel, qb_spike  -> to double check no kneels or spikes slipped through
#   aborted_play        -> botched snaps, reported in the checks
#   punt_fair_catch, punt_downed, punt_out_of_bounds -> to pick spot check punts
HELPER_COLS = [
    "down", "play_type", "desc", "qb_kneel", "qb_spike", "aborted_play",
    "punt_fair_catch", "punt_downed", "punt_out_of_bounds",
]

# ---------------------------------------------------------------
# Step 1: Confirm every column we need exists before loading
# ---------------------------------------------------------------
needed_cols = []
for col in FOURTH_DOWN_COLS + FIELD_GOAL_COLS + PUNT_COLS + HELPER_COLS:
    if col not in needed_cols:
        needed_cols.append(col)

available_cols = pq.read_schema(INPUT_FILE).names
print(f"Checking {len(needed_cols)} columns this script uses:")
missing = [col for col in needed_cols if col not in available_cols]
print(f"  {needed_cols}")
if missing:
    raise KeyError(f"These columns are missing from the data: {missing}. Stopping.")
print("  All columns found.\n")

# Load only the columns we need (much faster than loading all 372).
pbp = pd.read_parquet(INPUT_FILE, columns=needed_cols)
print(f"Loaded {len(pbp):,} regular season plays.\n")


def to_whole_numbers(df, cols):
    """Store columns like 4.0 as 4 so the CSV is easier to read.
    Int64 (capital I) allows blanks, in case a value is missing."""
    for col in cols:
        df[col] = df[col].astype("Int64")
    return df


# ===============================================================
# Part a) Go-for-it attempts on fourth down
# ===============================================================
# A go-for-it attempt is a fourth-down play that was a run or a pass.
# In nflfastR, play_type is already split so that these are separate values:
#   "no_play"  = a penalty wiped out the play
#   "qb_kneel" = a kneel down
#   "qb_spike" = a spike
# So keeping only "run" and "pass" removes no-plays, kneels, and spikes.
fourth = pbp[pbp["down"] == 4]
print("Fourth-down plays by play_type (before filtering):")
print(fourth["play_type"].value_counts(dropna=False).to_string(), "\n")

go = fourth[fourth["play_type"].isin(["run", "pass"])].copy()

# Double check: no kneels or spikes should be left.
print(f"Kneels left after filter: {int(go['qb_kneel'].sum())}, "
      f"spikes left after filter: {int(go['qb_spike'].sum())}")

go_out = to_whole_numbers(
    go[FOURTH_DOWN_COLS].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100", "ydstogo",
     "score_differential", "fourth_down_converted", "fourth_down_failed"],
)
go_out.to_csv(DATA_DIR / "fourth_down_attempts.csv", index=False)

print("\n========== CHECKS: fourth_down_attempts.csv ==========")
print(f"Rows: {len(go_out):,}")
print(f"Overall conversion rate: {go_out['fourth_down_converted'].mean():.3f}")

# Conversion rate by yards to go. Anything 10 or more goes in one "10+" group.
go_out["ydstogo_group"] = go_out["ydstogo"].clip(upper=10).astype(str)
go_out.loc[go_out["ydstogo_group"] == "10", "ydstogo_group"] = "10+"
by_ydstogo = go_out.groupby("ydstogo_group", sort=False).agg(
    attempts=("fourth_down_converted", "size"),
    conversion_rate=("fourth_down_converted", "mean"),
)
order = [str(i) for i in range(1, 10)] + ["10+"]
print("\nConversion rate by ydstogo:")
print(by_ydstogo.reindex(order).round(3).to_string())

# Extra info so we know what is inside this group of plays.
fake_punt = go["desc"].str.contains("punt formation", case=False)
fake_fg = go["desc"].str.contains("field goal formation", case=False)
neither = (go["fourth_down_converted"] == 0) & (go["fourth_down_failed"] == 0)
print("\nExtra info:")
print(f"  Plays run from punt formation (fake punts):   {int(fake_punt.sum())}")
print(f"  Plays run from field goal formation (fakes):  {int(fake_fg.sum())}")
print(f"  Aborted plays (botched snaps):                {int((go['aborted_play'] == 1).sum())}")
print(f"  Rows marked neither converted nor failed:     {int(neither.sum())}")


# ===============================================================
# Part b) Field goal attempts
# ===============================================================
fg = pbp[pbp["play_type"] == "field_goal"].copy()

# made = 1 if the kick was good, 0 if it was missed or blocked.
fg["made"] = (fg["field_goal_result"] == "made").astype(int)

fg_out = to_whole_numbers(
    fg[FIELD_GOAL_COLS + ["made"]].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100",
     "kick_distance", "score_differential"],
)
fg_out.to_csv(DATA_DIR / "field_goals.csv", index=False)

print("\n========== CHECKS: field_goals.csv ==========")
print(f"Rows: {len(fg_out):,}")
print(f"field_goal_result values: {fg_out['field_goal_result'].value_counts().to_dict()}")
print(f"Overall make rate: {fg_out['made'].mean():.3f}")

# 5-yard buckets: 20-24, 25-29, and so on.
bucket_start = (fg_out["kick_distance"] // 5) * 5
fg_out["distance_bucket"] = bucket_start.astype(str) + "-" + (bucket_start + 4).astype(str)
by_distance = (
    fg_out.assign(bucket_start=bucket_start)
    .groupby(["bucket_start", "distance_bucket"])
    .agg(attempts=("made", "size"), make_rate=("made", "mean"))
    .reset_index(level="bucket_start", drop=True)
)
print("\nMake rate by kick distance (yards):")
print(by_distance.round(3).to_string())

print("\nExtra info: field goal attempts by down "
      "(non-4th-down kicks are mostly end of half or end of game):")
print(fg["down"].value_counts(dropna=False).sort_index().to_string())


# ===============================================================
# Part c) Punts
# ===============================================================
punts = pbp[pbp["play_type"] == "punt"].copy()

# HOW net_punt_yards IS CALCULATED
# net_punt_yards = how many yards the ball moved toward the receiving team's
# own end zone, from where the punt started to where the receiving team gets it.
#
#   Touchback (touchback == 1):
#       The receiving team gets the ball at their own 20 yard line.
#       The punt started yardline_100 yards away from their end zone, so
#           net_punt_yards = yardline_100 - 20
#       Example: punt from the opponent's 45 (yardline_100 = 45) into the
#       end zone, touchback, ball at the 20. Net = 45 - 20 = 25 yards.
#       (We do not use kick_distance here because for touchbacks nflfastR only
#       counts the kick up to the goal line.)
#
#   Every other punt:
#           net_punt_yards = kick_distance - return_yards
#       kick_distance = how far the punt went from the line of scrimmage to
#       where it was caught, downed, or went out of bounds.
#       return_yards  = how far the returner ran it back (0 for fair catches,
#       downed punts, and out of bounds punts). A return for negative yards
#       makes the net bigger.
#       Example: 50-yard punt returned 8 yards. Net = 50 - 8 = 42 yards.
#
#   NOT counted: penalty yards (for example holding on the return).
#   Blocked punts have kick_distance = 0 in the data, so their net is near 0.
punts["net_punt_yards"] = np.where(
    punts["touchback"] == 1,
    punts["yardline_100"] - 20,
    punts["kick_distance"] - punts["return_yards"],
)

punt_out = to_whole_numbers(
    punts[PUNT_COLS + ["net_punt_yards"]].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100", "kick_distance",
     "return_yards", "touchback", "punt_blocked", "score_differential", "net_punt_yards"],
)
punt_out.to_csv(DATA_DIR / "punts.csv", index=False)

print("\n========== CHECKS: punts.csv ==========")
print(f"Rows: {len(punt_out):,}")
print(f"Touchbacks: {int(punts['touchback'].sum())}, blocked: {int(punts['punt_blocked'].sum())}")
print(f"net_punt_yards mean: {punt_out['net_punt_yards'].mean():.2f}")
print(f"net_punt_yards std:  {punt_out['net_punt_yards'].std():.2f}")
not_blocked = punt_out[punt_out["punt_blocked"] == 0]["net_punt_yards"]
print(f"Without blocked punts: mean {not_blocked.mean():.2f}, std {not_blocked.std():.2f}")
print(f"Min: {punt_out['net_punt_yards'].min()}, max: {punt_out['net_punt_yards'].max()}")

# Spot check: one real punt of each common type, with the play description,
# so we can read the text and confirm our number is right.
print("\nSpot check (play description next to our net_punt_yards):")
returned = (punts["return_yards"] > 0) & (punts["touchback"] == 0)
spot_check_groups = {
    "Fair catch": punts["punt_fair_catch"] == 1,
    "Returned": returned,
    "Touchback": punts["touchback"] == 1,
    "Downed": punts["punt_downed"] == 1,
    "Out of bounds": punts["punt_out_of_bounds"] == 1,
}
for label, rows in spot_check_groups.items():
    p = punts[rows].sample(1, random_state=4520).iloc[0]
    print(f"\n  [{label}] yardline_100={p['yardline_100']:.0f}, "
          f"kick_distance={p['kick_distance']:.0f}, return_yards={p['return_yards']:.0f}, "
          f"touchback={p['touchback']:.0f}  ->  net_punt_yards={p['net_punt_yards']:.0f}")
    print(f"  desc: {p['desc']}")

# Histogram with a normal curve on top (same mean and std) for comparison.
values = not_blocked.astype(float)
mean, std = values.mean(), values.std()
fig, ax = plt.subplots(figsize=(9, 5))
bins = np.arange(values.min() - 0.5, values.max() + 1.5, 1)  # one bar per yard
ax.hist(values, bins=bins, density=True, color="#4C72B0", alpha=0.75, label="Actual punts")
x = np.linspace(values.min(), values.max(), 400)
normal_curve = np.exp(-0.5 * ((x - mean) / std) ** 2) / (std * np.sqrt(2 * np.pi))
ax.plot(x, normal_curve, color="#C44E52", linewidth=2,
        label=f"Normal curve (mean {mean:.1f}, std {std:.1f})")
ax.set_xlabel("Net punt yards")
ax.set_ylabel("Share of punts")
ax.set_title(f"Net punt yards, 2018 to 2025 regular season ({len(values):,} punts, blocked punts left out)")
ax.legend()
fig.tight_layout()
fig.savefig(DATA_DIR / "net_punt_hist.png", dpi=150)
print(f"\nHistogram saved to: {DATA_DIR / 'net_punt_hist.png'}")
