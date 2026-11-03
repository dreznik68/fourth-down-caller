"""
03_build_drives.py

What this script does:
    Builds a drive table with one row per drive, from the regular season
    play-by-play file made by 01_pull_pbp.py. For each drive it records where
    and when it started, the score at the start, how it ended, how many points
    the offense scored, and whether (and where) it faced a fourth down.
    Saves the result to data/drives.csv and prints checks.

How to run (from the project root folder):
    python3 code/03_build_drives.py

Needs:
    data/pbp_2018_2025.parquet (run 01_pull_pbp.py first)

Key definitions (read these before using the table):
    Drive:
        nflfastR's fixed_drive number inside each game. A drive is one
        (game_id, fixed_drive) pair.
    Snap:
        A play from scrimmage, meaning any row where `down` is filled in (1 to 4).
        Kickoffs, extra points, two-point tries, timeouts, and end-of-quarter
        rows have no down, so they are not snaps.
    Drive start:
        The drive's first snap. We skip the kickoff because nflfastR puts the
        kickoff row inside the receiving team's drive with yardline_100 = 35,
        which is not where the offense actually started.
        Drives with no snap at all are left out (see the checks for how many).
    Fourth-down play:
        A snap with down == 4 that actually counted. Plays wiped out by a
        penalty (play_type "no_play") are not counted.
"""

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

# ---------------------------------------------------------------
# File paths
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_FILE = DATA_DIR / "pbp_2018_2025.parquet"
OUTPUT_FILE = DATA_DIR / "drives.csv"

# One drive = one (game_id, fixed_drive) pair.
DRIVE_KEY = ["game_id", "fixed_drive"]

# ---------------------------------------------------------------
# Step 1: Confirm every column we need exists before loading
# ---------------------------------------------------------------
needed_cols = [
    "game_id", "play_id", "season", "posteam", "defteam",
    "fixed_drive", "fixed_drive_result",
    "down", "play_type", "yardline_100", "ydstogo",
    "game_seconds_remaining", "qtr", "score_differential",
    "posteam_score", "posteam_score_post",
]
available_cols = pq.read_schema(INPUT_FILE).names
print(f"Checking {len(needed_cols)} columns this script uses:")
print(f"  {needed_cols}")
missing = [col for col in needed_cols if col not in available_cols]
if missing:
    raise KeyError(f"These columns are missing from the data: {missing}. Stopping.")
print("  All columns found.\n")

pbp = pd.read_parquet(INPUT_FILE, columns=needed_cols)

# Put plays in the order they happened inside each game.
pbp = pbp.sort_values(["game_id", "play_id"]).reset_index(drop=True)
print(f"Loaded {len(pbp):,} regular season plays from {pbp['game_id'].nunique():,} games.\n")

print("Unique values of fixed_drive_result (count of plays with each value):")
print(pbp["fixed_drive_result"].value_counts(dropna=False).to_string(), "\n")

# ---------------------------------------------------------------
# Step 2: Find the first snap of each drive (this is the drive start)
# ---------------------------------------------------------------
snaps = pbp[pbp["down"].notna()]

# Since plays are sorted in order, the first row of each drive is its first snap.
first_snap = snaps.drop_duplicates(subset=DRIVE_KEY, keep="first")

drives = first_snap[[
    "game_id", "season", "posteam", "defteam", "fixed_drive",
    "yardline_100", "game_seconds_remaining", "qtr",
    "score_differential", "fixed_drive_result",
]].rename(columns={
    "yardline_100": "start_yardline_100",
    "game_seconds_remaining": "start_game_seconds_remaining",
    "qtr": "start_qtr",
    # score_differential in nflfastR is already from the offense's (posteam) view:
    # positive means the offense is ahead.
    "score_differential": "start_score_differential",
    "fixed_drive_result": "drive_result",
})

# How many drive numbers had no snap at all (left out of the table)?
all_drive_ids = pbp[DRIVE_KEY].drop_duplicates()
no_snap_ids = all_drive_ids.merge(drives[DRIVE_KEY], on=DRIVE_KEY, how="left", indicator=True)
no_snap_ids = no_snap_ids[no_snap_ids["_merge"] == "left_only"][DRIVE_KEY]
no_snap_results = pbp.merge(no_snap_ids, on=DRIVE_KEY).drop_duplicates(DRIVE_KEY)["fixed_drive_result"]

# ---------------------------------------------------------------
# Step 3: Points scored by the offense on each drive
# ---------------------------------------------------------------
# On every play, posteam_score is the offense's score before the play and
# posteam_score_post is its score after. The difference is the points the
# offense scored on that play (6 for a TD, 1 for an extra point, and so on).
# We add this up over the drive, but only on rows where the team with the ball
# is the drive's offense. That way points the defense scores (pick six,
# safety) do not count for the offense.
pbp["points_on_play"] = pbp["posteam_score_post"] - pbp["posteam_score"]

rows = pbp.merge(
    drives[DRIVE_KEY + ["posteam"]].rename(columns={"posteam": "drive_offense"}),
    on=DRIVE_KEY,
)
offense_rows = rows[rows["posteam"] == rows["drive_offense"]]
points = offense_rows.groupby(DRIVE_KEY)["points_on_play"].sum().rename("points_scored")
drives = drives.merge(points, on=DRIVE_KEY, how="left")

# ---------------------------------------------------------------
# Step 4: Fourth downs on each drive
# ---------------------------------------------------------------
is_fourth_down_play = (
    (pbp["down"] == 4)
    & pbp["play_type"].notna()
    & (pbp["play_type"] != "no_play")
)
fourth = pbp[is_fourth_down_play]

num_fourth = fourth.groupby(DRIVE_KEY).size().rename("num_fourth_downs")

first_fourth = fourth.drop_duplicates(subset=DRIVE_KEY, keep="first")[
    DRIVE_KEY + ["yardline_100", "ydstogo"]
].rename(columns={
    "yardline_100": "first_4th_yardline_100",
    "ydstogo": "first_4th_ydstogo",
})

drives = drives.merge(num_fourth, on=DRIVE_KEY, how="left")
drives = drives.merge(first_fourth, on=DRIVE_KEY, how="left")
drives["num_fourth_downs"] = drives["num_fourth_downs"].fillna(0)
drives["reached_fourth_down"] = (drives["num_fourth_downs"] > 0).astype(int)

# ---------------------------------------------------------------
# Step 5: Tidy up and save
# ---------------------------------------------------------------
drives = drives[[
    "game_id", "season", "posteam", "defteam", "fixed_drive",
    "start_yardline_100", "start_game_seconds_remaining", "start_qtr",
    "start_score_differential", "drive_result", "points_scored",
    "reached_fourth_down", "first_4th_yardline_100", "first_4th_ydstogo",
    "num_fourth_downs",
]]

# Store whole numbers as 4 instead of 4.0. Int64 (capital I) allows blanks,
# which we need for first_4th_* on drives that never reached fourth down.
for col in ["season", "fixed_drive", "start_yardline_100", "start_game_seconds_remaining",
            "start_qtr", "start_score_differential", "points_scored", "reached_fourth_down",
            "first_4th_yardline_100", "first_4th_ydstogo", "num_fourth_downs"]:
    drives[col] = drives[col].astype("Int64")

drives.to_csv(OUTPUT_FILE, index=False)

# ---------------------------------------------------------------
# Checks
# ---------------------------------------------------------------
n_games = pbp["game_id"].nunique()
print("========== CHECKS: drives.csv ==========")
print(f"Total drives: {len(drives):,}")
print(f"Drive numbers left out because they had no snap: {len(no_snap_ids):,}")
print("  Their fixed_drive_result values:")
print("  " + no_snap_results.value_counts(dropna=False).to_string().replace("\n", "\n  "))
print(f"Average drives per team per game: {len(drives) / (2 * n_games):.2f} "
      f"({len(drives):,} drives / {n_games:,} games / 2 teams)")

print("\nShare of each drive_result:")
shares = drives["drive_result"].value_counts(dropna=False)
print(pd.DataFrame({"drives": shares, "share": (shares / len(drives)).round(4)}).to_string())

reached = drives[drives["reached_fourth_down"] == 1]
two_plus = drives[drives["num_fourth_downs"] >= 2]
print(f"\nDrives that reached fourth down: {len(reached):,} ({len(reached) / len(drives):.3f} of all drives)")
print(f"Drives with 2 or more fourth downs: {len(two_plus):,} "
      f"({len(two_plus) / len(drives):.3f} of all drives, "
      f"{len(two_plus) / len(reached):.3f} of drives that reached fourth down)")
print("Number of fourth downs per drive:")
print(drives["num_fourth_downs"].value_counts().sort_index().to_string())

print("\nCross-check: points_scored for each drive_result "
      "(TD should be 6/7/8, FG should be 3, most others 0):")
print(pd.crosstab(drives["drive_result"], drives["points_scored"]).to_string())

# Drives where nflfastR gave snaps by two different offenses the same drive number.
offenses_per_drive = snaps.groupby(DRIVE_KEY)["posteam"].nunique()
print(f"\nDrives whose snaps have more than one offense (data issue): "
      f"{int((offenses_per_drive > 1).sum())}")
print(f"\nSaved to: {OUTPUT_FILE}")
