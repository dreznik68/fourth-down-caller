"""
01_pull_pbp.py

What this script does:
    1. Downloads NFL play-by-play data (nflfastR) for the 2018 through 2025 seasons.
    2. Keeps only regular season games (drops preseason and playoffs).
    3. Saves the result to data/pbp_2018_2025.parquet so the other scripts can use it.

How to run (from the project root folder):
    python3 code/01_pull_pbp.py

Output:
    data/pbp_2018_2025.parquet
"""

from pathlib import Path

import nflreadpy as nfl
import polars as pl

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
FIRST_SEASON = 2018
LAST_SEASON = 2025

# Build file paths relative to this script, so it works no matter
# which folder you run it from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "pbp_2018_2025.parquet"

# Make sure the data folder exists.
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------
# Step 1: Download the play-by-play data
# ---------------------------------------------------------------
seasons = list(range(FIRST_SEASON, LAST_SEASON + 1))
print(f"Downloading play-by-play for seasons: {seasons}")

# load_pbp returns one Polars DataFrame with every play from every season.
pbp = nfl.load_pbp(seasons)
print(f"Downloaded {pbp.height:,} plays and {pbp.width} columns (all season types).")

# ---------------------------------------------------------------
# Step 2: Confirm the columns we need actually exist
# ---------------------------------------------------------------
needed_columns = ["season", "season_type"]
print(f"\nColumns this script uses: {needed_columns}")
for col in needed_columns:
    if col in pbp.columns:
        print(f"  found:   {col}")
    else:
        raise KeyError(f"Column '{col}' is missing from the data. Stopping.")

print(f"season_type values before filtering: {sorted(pbp['season_type'].unique().to_list())}")

# ---------------------------------------------------------------
# Step 3: Keep regular season games only
# ---------------------------------------------------------------
pbp_reg = pbp.filter(pl.col("season_type") == "REG")
print(f"\nKept {pbp_reg.height:,} regular season plays "
      f"(dropped {pbp.height - pbp_reg.height:,} non-regular-season plays).")

# ---------------------------------------------------------------
# Step 4: Save to parquet
# ---------------------------------------------------------------
# Parquet is a compressed file format that loads much faster than CSV.
pbp_reg.write_parquet(OUTPUT_FILE)

# ---------------------------------------------------------------
# Checks
# ---------------------------------------------------------------
print("\n========== CHECKS ==========")
print(f"Total rows: {pbp_reg.height:,}")
print(f"Total columns: {pbp_reg.width}")

print("\nRows and games per season:")
per_season = (
    pbp_reg.group_by("season")
    .agg(
        pl.len().alias("rows"),
        pl.col("game_id").n_unique().alias("games"),
    )
    .sort("season")
)
for row in per_season.iter_rows(named=True):
    print(f"  {row['season']}: {row['rows']:>7,} rows, {row['games']} games")

file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
print(f"\nSaved to: {OUTPUT_FILE}")
print(f"File size: {file_size_mb:.1f} MB")
