"""
02_filter_plays.py

What this script does:
    Reads the regular season play-by-play file made by 01_pull_pbp.py and
    splits out the three kinds of fourth-down decisions we care about:
        a) go-for-it attempts  -> data/fourth_down_attempts.csv
        b) field goal attempts -> data/field_goals.csv
        c) punts               -> data/punts.csv
    For punts it also builds the net punt yards distribution for each
    starting field position bucket:
        data/punt_distribution_by_bucket.csv  (count and probability of each net yards bucket)
        data/punt_mean_sd_by_bucket.csv       (mean and SD of net yards per start bucket)
        data/net_punt_hist.png                (histogram of net punt yards)
    It prints checks (row counts and rates) for each file.

    No rows are deleted. Plays we leave out of the estimates are marked with
    flag columns (1 = yes, 0 = no) so every exclusion can be traced.

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
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_FILE = DATA_DIR / "pbp_2018_2025.parquet"

# Bucket size (in yards) for field position and net punt yards.
# A bucket is named by its lowest value: bucket 40 means 40 to 44 yards.
BUCKET_SIZE = 5

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

# Extra columns used only for filtering, flags, and checks (not saved to the CSVs).
#   play_id, down, play_type -> to put plays in order and pick the plays
#   desc                     -> the text description of the play
#   qb_kneel, qb_spike       -> to double check no kneels or spikes slipped through
#   aborted_play             -> botched snaps
#   penalty, fumble_lost     -> punt flags
#   touchdown, safety        -> to score blocked punts correctly
#   punt_fair_catch, punt_downed, punt_out_of_bounds -> to pick spot check punts
HELPER_COLS = [
    "play_id", "down", "play_type", "desc", "qb_kneel", "qb_spike", "aborted_play",
    "penalty", "fumble_lost", "touchdown", "safety",
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

# Load only the columns we need (much faster than loading all 372),
# and put plays in the order they happened inside each game.
pbp = pd.read_parquet(INPUT_FILE, columns=needed_cols)
pbp = pbp.sort_values(["game_id", "play_id"]).reset_index(drop=True)
print(f"Loaded {len(pbp):,} regular season plays.\n")


def to_whole_numbers(df, cols):
    """Store columns like 4.0 as 4 so the CSV is easier to read.
    Int64 (capital I) allows blanks, in case a value is missing."""
    for col in cols:
        df[col] = df[col].astype("Int64")
    return df


def bucket(values):
    """Round each value down to the start of its bucket. With 5-yard buckets:
    43 -> 40, 45 -> 45, -3 -> -5."""
    return (np.floor(values / BUCKET_SIZE) * BUCKET_SIZE).astype(int)


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

# Flags (1 = yes, 0 = no). These plays stay in the CSV, but they are left out
# of the conversion rate, because our "go for it" means the offense lining up
# to go for it. Fakes convert at a different rate because of surprise.
#   is_fake_kick:    the play was run from punt or field goal formation.
#                    nflfastR writes "(Punt formation)" or "(Field Goal formation)"
#                    in the play description.
#   is_botched_snap: nflfastR marked the play as aborted (bad snap or exchange).
go["is_fake_kick"] = go["desc"].str.contains(
    "punt formation|field goal formation", case=False).astype(int)
go["is_botched_snap"] = (go["aborted_play"] == 1).astype(int)

go_out = to_whole_numbers(
    go[FOURTH_DOWN_COLS + ["is_fake_kick", "is_botched_snap"]].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100", "ydstogo",
     "score_differential", "fourth_down_converted", "fourth_down_failed"],
)
go_out.to_csv(DATA_DIR / "fourth_down_attempts.csv", index=False)

# The plays we use for estimates: not a fake kick and not a botched snap.
go_est = go_out[(go_out["is_fake_kick"] == 0) & (go_out["is_botched_snap"] == 0)].copy()

print("\n========== CHECKS: fourth_down_attempts.csv ==========")
print(f"Rows in file: {len(go_out):,}")
fake = go_out["is_fake_kick"] == 1
botched = go_out["is_botched_snap"] == 1
print(f"  is_fake_kick = 1:    {int(fake.sum())}")
print(f"  is_botched_snap = 1: {int(botched.sum())}")
print(f"  both flags = 1:      {int((fake & botched).sum())}")
print(f"  either flag = 1:     {int((fake | botched).sum())}")
print(f"Plays used for estimates (neither flag): {len(go_est):,}")
print(f"Overall conversion rate (estimate plays): {go_est['fourth_down_converted'].mean():.3f}")
print(f"  for comparison, all {len(go_out):,} plays: {go_out['fourth_down_converted'].mean():.3f}")
fake_only = go_out[fake & ~botched]
print(f"  for comparison, fake kicks that were not botched ({len(fake_only)}): "
      f"{fake_only['fourth_down_converted'].mean():.3f}")

# Conversion rate by yards to go. Anything 10 or more goes in one "10+" group.
go_est["ydstogo_group"] = go_est["ydstogo"].clip(upper=10).astype(str)
go_est.loc[go_est["ydstogo_group"] == "10", "ydstogo_group"] = "10+"
by_ydstogo = go_est.groupby("ydstogo_group", sort=False).agg(
    attempts=("fourth_down_converted", "size"),
    conversion_rate=("fourth_down_converted", "mean"),
)
order = [str(i) for i in range(1, 10)] + ["10+"]
print("\nConversion rate by ydstogo (estimate plays):")
print(by_ydstogo.reindex(order).round(3).to_string())

neither = (go_out["fourth_down_converted"] == 0) & (go_out["fourth_down_failed"] == 0)
print(f"\nRows marked neither converted nor failed: {int(neither.sum())}")


# ===============================================================
# Part b) Field goal attempts
# ===============================================================
fg = pbp[pbp["play_type"] == "field_goal"].copy()

# made = 1 if the kick was good, 0 if it was missed or blocked.
fg["made"] = (fg["field_goal_result"] == "made").astype(int)

# on_fourth_down = 1 if the kick was on 4th down. Kicks on other downs are
# mostly at the end of a half. We use ALL kicks for the make rate, because
# the kick itself does not depend on the down.
fg["on_fourth_down"] = (fg["down"] == 4).astype(int)

fg_out = to_whole_numbers(
    fg[FIELD_GOAL_COLS + ["made", "on_fourth_down"]].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100",
     "kick_distance", "score_differential"],
)
fg_out.to_csv(DATA_DIR / "field_goals.csv", index=False)

print("\n========== CHECKS: field_goals.csv ==========")
print(f"Rows: {len(fg_out):,}")
print(f"on_fourth_down = 1: {int(fg_out['on_fourth_down'].sum()):,}, "
      f"on_fourth_down = 0: {int((fg_out['on_fourth_down'] == 0).sum()):,}")
print(f"field_goal_result values: {fg_out['field_goal_result'].value_counts().to_dict()}")
print(f"Overall make rate, all kicks: {fg_out['made'].mean():.3f}")
print(f"Overall make rate, 4th down only: "
      f"{fg_out.loc[fg_out['on_fourth_down'] == 1, 'made'].mean():.3f}")

# Make rate by 5-yard kick distance bucket, both ways, side by side.
fg_out["distance_bucket"] = bucket(fg_out["kick_distance"].astype(float))
all_kicks = fg_out.groupby("distance_bucket").agg(
    attempts_all=("made", "size"), make_rate_all=("made", "mean"))
fourth_only = fg_out[fg_out["on_fourth_down"] == 1].groupby("distance_bucket").agg(
    attempts_4th=("made", "size"), make_rate_4th=("made", "mean"))
by_distance = all_kicks.join(fourth_only)
by_distance["difference"] = by_distance["make_rate_all"] - by_distance["make_rate_4th"]
by_distance.index = [f"{b}-{b + BUCKET_SIZE - 1}" for b in by_distance.index]
by_distance.index.name = "kick_distance"
print("\nMake rate by kick distance (yards), all kicks vs 4th down only:")
print(by_distance.round(3).to_string())


# ===============================================================
# Part c) Punts
# ===============================================================
punts = pbp[pbp["play_type"] == "punt"].copy()

# For each punt, find the next snap in the same game. We use it below to see
# where the receiving team actually took over after a blocked punt.
snaps = pbp[pbp["down"].notna()].copy()
snaps["next_snap_posteam"] = snaps.groupby("game_id")["posteam"].shift(-1)
snaps["next_snap_yardline_100"] = snaps.groupby("game_id")["yardline_100"].shift(-1)
punts = punts.join(snaps[["next_snap_posteam", "next_snap_yardline_100"]])

# HOW net_punt_yards IS CALCULATED
# net_punt_yards = how many yards the ball moved toward the receiving team's
# own end zone, from where the punt started to where the play ended.
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
#   Blocked punt (punt_blocked == 1):
#       nflfastR records kick_distance = 0 and return_yards = 0 for every
#       blocked punt, so the normal formula would give 0. Instead we use where
#       the ball really ended up:
#       - If the defense scored (touchdown or safety), the ball ended in the
#         punting team's end zone: net_punt_yards = yardline_100 - 100
#         (a negative number). This matches how punt return touchdowns come
#         out of the normal formula below.
#       - Otherwise, the spot of the receiving team's next snap. That snap is
#         next_snap_yardline_100 yards from the punting team's end zone, which
#         is 100 - next_snap_yardline_100 yards from their own end zone, so
#             net_punt_yards = yardline_100 - (100 - next_snap_yardline_100)
#         Example: punt from own 13 (yardline_100 = 87) is blocked and the
#         opponent takes over at our 6 (next_snap_yardline_100 = 6).
#         Net = 87 - (100 - 6) = -7 yards.
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
#   NOT counted: penalty yards. Punts with a penalty are flagged below and
#   left out of the distribution.
blocked = punts["punt_blocked"] == 1
defense_scored = (punts["touchdown"] == 1) | (punts["safety"] == 1)
receiving_team_next = punts["next_snap_posteam"] == punts["defteam"]

punts["net_punt_yards"] = np.where(
    punts["touchback"] == 1,
    punts["yardline_100"] - 20,
    punts["kick_distance"] - punts["return_yards"],
)
punts.loc[blocked & defense_scored, "net_punt_yards"] = punts["yardline_100"] - 100
punts.loc[blocked & ~defense_scored & receiving_team_next, "net_punt_yards"] = (
    punts["yardline_100"] - (100 - punts["next_snap_yardline_100"])
)
# If a blocked punt fits neither case, we leave it blank so it is easy to spot.
blocked_unscored = blocked & ~defense_scored & ~receiving_team_next
punts.loc[blocked_unscored, "net_punt_yards"] = np.nan

# Flags (1 = yes, 0 = no):
#   has_penalty:         a penalty was called on the punt. Penalty yards move
#                        the ball, and our net does not count them, so these
#                        are left out of the distribution.
#   is_blocked:          the punt was blocked. Kept IN the distribution,
#                        because a block is a real outcome of choosing to punt.
#   is_muffed_recovered: the returner muffed the punt and the punting team got
#                        the ball back (desc says "MUFFS" and the receiving team
#                        lost the fumble). The punting team keeps the ball, so
#                        this is not a normal change of possession. Left out.
punts["has_penalty"] = (punts["penalty"] == 1).astype(int)
punts["is_blocked"] = blocked.astype(int)
punts["is_muffed_recovered"] = (
    punts["desc"].str.contains("MUFFS") & (punts["fumble_lost"] == 1)
).astype(int)

punt_out = to_whole_numbers(
    punts[PUNT_COLS + ["net_punt_yards", "has_penalty", "is_blocked", "is_muffed_recovered"]].copy(),
    ["season", "qtr", "game_seconds_remaining", "yardline_100", "kick_distance",
     "return_yards", "touchback", "punt_blocked", "score_differential", "net_punt_yards"],
)
punt_out.to_csv(DATA_DIR / "punts.csv", index=False)

# The punts we use for the distribution: no penalty and not a recovered muff.
punt_est = punt_out[(punt_out["has_penalty"] == 0) & (punt_out["is_muffed_recovered"] == 0)].copy()

print("\n========== CHECKS: punts.csv ==========")
print(f"Rows in file: {len(punt_out):,}")
print(f"  has_penalty = 1:         {int(punt_out['has_penalty'].sum()):,}")
print(f"  is_blocked = 1:          {int(punt_out['is_blocked'].sum()):,} "
      f"(defense scored on {int((blocked & defense_scored).sum())}, "
      f"receiving team took over on {int((blocked & ~defense_scored & receiving_team_next).sum())}, "
      f"left blank {int(blocked_unscored.sum())})")
print(f"  is_muffed_recovered = 1: {int(punt_out['is_muffed_recovered'].sum()):,}")
print(f"  penalty AND muffed recovered: "
      f"{int(((punt_out['has_penalty'] == 1) & (punt_out['is_muffed_recovered'] == 1)).sum())}")
print(f"Punts used for the distribution (no penalty, not a recovered muff): {len(punt_est):,}")
print(f"  of these, blocked: {int(punt_est['is_blocked'].sum())}")
print(f"net_punt_yards, distribution punts: mean {punt_est['net_punt_yards'].mean():.2f}, "
      f"SD {punt_est['net_punt_yards'].std():.2f}, "
      f"min {punt_est['net_punt_yards'].min()}, max {punt_est['net_punt_yards'].max()}")

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
    "Blocked, receiving team took over": blocked & ~defense_scored & receiving_team_next,
    "Blocked, defense scored": blocked & defense_scored,
}
for label, rows in spot_check_groups.items():
    p = punts[rows].sample(1, random_state=4520).iloc[0]
    print(f"\n  [{label}] yardline_100={p['yardline_100']:.0f}, "
          f"kick_distance={p['kick_distance']:.0f}, return_yards={p['return_yards']:.0f}, "
          f"touchback={p['touchback']:.0f}  ->  net_punt_yards={p['net_punt_yards']:.0f}")
    print(f"  desc: {p['desc']}")

# ---------------------------------------------------------------
# Net punt yards distribution for each starting field position bucket
# ---------------------------------------------------------------
# start_bucket:     yardline_100 where the punt started, rounded down to a
#                   5-yard bucket (start_bucket 40 = yardline_100 from 40 to 44).
# net_yards_bucket: net_punt_yards rounded down to a 5-yard bucket
#                   (net_yards_bucket 35 = 35 to 39 net yards, -5 = -5 to -1).
# probability:      share of punts from that start_bucket that landed in that
#                   net_yards_bucket. Adds up to 1 within each start_bucket.
punt_est["start_bucket"] = bucket(punt_est["yardline_100"].astype(float))
punt_est["net_yards_bucket"] = bucket(punt_est["net_punt_yards"].astype(float))

dist = (
    punt_est.groupby(["start_bucket", "net_yards_bucket"])
    .size()
    .rename("count")
    .reset_index()
)
dist["probability"] = dist["count"] / dist.groupby("start_bucket")["count"].transform("sum")
dist.to_csv(DATA_DIR / "punt_distribution_by_bucket.csv", index=False)

# Mean and SD of net punt yards for each start bucket.
mean_sd = (
    punt_est.groupby("start_bucket")["net_punt_yards"]
    .agg(punts="size", mean_net_yards="mean", sd_net_yards="std")
    .round(2)
    .reset_index()
)
mean_sd.to_csv(DATA_DIR / "punt_mean_sd_by_bucket.csv", index=False)

print("\n========== CHECKS: punt_distribution_by_bucket.csv ==========")
print(f"Rows: {len(dist):,} (one per start_bucket and net_yards_bucket pair that happened)")
sums = dist.groupby("start_bucket")["probability"].sum()
print(f"Probabilities sum to 1 in every start_bucket: {bool(np.allclose(sums, 1.0))} "
      f"(smallest sum {sums.min():.6f}, largest {sums.max():.6f})")

print("\n========== CHECKS: punt_mean_sd_by_bucket.csv ==========")
print("start_bucket = yardline_100 where the punt started (40 means 40 to 44)")
print(mean_sd.to_string(index=False))
small = mean_sd[mean_sd["punts"] < 50]
if len(small) > 0:
    print(f"Note: start buckets with fewer than 50 punts: {small['start_bucket'].tolist()}")

# Histogram of net punt yards for the distribution punts (one bar per yard).
values = punt_est["net_punt_yards"].astype(float)
fig, ax = plt.subplots(figsize=(9, 5))
bins = np.arange(values.min() - 0.5, values.max() + 1.5, 1)
ax.hist(values, bins=bins, color="#4C72B0")
ax.set_xlabel("Net punt yards")
ax.set_ylabel("Number of punts")
ax.set_title(f"Net punt yards, 2018 to 2025 regular season "
             f"({len(values):,} punts, no penalties or recovered muffs)")
fig.tight_layout()
fig.savefig(DATA_DIR / "net_punt_hist.png", dpi=150)
print(f"\nHistogram saved to: {DATA_DIR / 'net_punt_hist.png'}")
