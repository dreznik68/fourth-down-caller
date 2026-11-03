# 4th Down Caller

IE 4520 (Stochastic Modeling) Group 4 class project.

We are building a probabilistic dynamic program that recommends the best NFL fourth-down call (go for it, kick a field goal, or punt) by picking the option that gives the highest chance of winning the game.

**Status (week of Nov 2):** the data is pulled and cleaned. The dynamic program model is not built yet.

**Website:** https://dreznik68.github.io/fourth-down-caller/

## Folder layout

```
fourth-down-caller/
  code/              Python scripts (run them in number order)
  data/              data files (NOT on GitHub, see "Getting the data" below)
  docs/              the website (GitHub Pages publishes from this folder)
  requirements.txt   list of Python packages the scripts need
  README.md          this file
  .gitignore         tells git which files to skip (including data/)
```

## Setup (one time)

You need Python 3. On a Mac, type `python3` (not `python`) in Terminal.

Open Terminal in the project folder and run:

```
python3 -m pip install -r requirements.txt
```

This installs:
- **nflreadpy**: downloads the NFL play-by-play data
- **pandas** and **polars**: work with data tables
- **pyarrow**: reads and writes `.parquet` files
- **matplotlib**: makes charts

## Getting the data

The `data/` folder is not on GitHub because the files are too big (the main file is about 94 MB). There are two ways to get it:

1. **Recreate it** by running the three scripts below. Script 1 needs an internet connection.
2. **Download it** from our shared Google Drive folder and put the files in a folder named `data` inside the project folder.

## Running the scripts

From the project folder, run these in order:

| Order | Command | What it makes |
|---|---|---|
| 1 | `python3 code/01_pull_pbp.py` | `data/pbp_2018_2025.parquet` (every regular season play, 2018 to 2025) |
| 2 | `python3 code/02_filter_plays.py` | `data/fourth_down_attempts.csv`, `data/field_goals.csv`, `data/punts.csv`, `data/net_punt_hist.png` |
| 3 | `python3 code/03_build_drives.py` | `data/drives.csv` |

Scripts 2 and 3 read the file that script 1 makes, so run script 1 first. Each script prints checks (row counts, rates) when it finishes.

## What is in each data file

| File | One row per | Rows |
|---|---|---|
| `pbp_2018_2025.parquet` | play (all 372 nflfastR columns) | 371,798 |
| `fourth_down_attempts.csv` | fourth-down run or pass (going for it) | 5,750 |
| `field_goals.csv` | field goal attempt | 8,241 |
| `punts.csv` | punt | 16,794 |
| `drives.csv` | drive | 46,363 |

Data source: [nflfastR](https://www.nflfastr.com/) play-by-play, loaded with the [nflreadpy](https://github.com/nflverse/nflreadpy) Python package. Regular season games only.

## Good to know about the data

- **net_punt_yards** (in `punts.csv`): for a touchback it is `yardline_100 - 20`. For every other punt it is `kick_distance - return_yards`. Penalty yards are not included.
- **fourth_down_attempts.csv** includes fake punts and fake field goals (206 plays), because they are runs or passes on fourth down.
- **field_goals.csv** includes 724 kicks that were not on fourth down (mostly at the end of a half).
- **drives.csv**: a drive starts at its first snap, not the kickoff. Fourth-down plays wiped out by a penalty are not counted in `num_fourth_downs`.
