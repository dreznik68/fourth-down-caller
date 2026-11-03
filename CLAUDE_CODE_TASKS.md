# IE 4520 Group 4: Week of Nov 2 Tasks (for Claude Code)

## Context
This repo is for a Stochastic Modeling class project: a probabilistic dynamic program that recommends the best NFL fourth-down call (go for it, field goal, or punt) to maximize win probability. This week is data and setup only. Do not build the DP model yet.

Data source: nflfastR play-by-play, loaded in Python with `nflreadpy` (`import nflreadpy as nfl`). It returns Polars DataFrames; `.to_pandas()` is fine if easier.

Machine: Mac. Use `python3`, not `python`.

## How to work
- Do the tasks in order.
- **Stop after each task.** Show me what you made, the row counts, and the checks listed for that task. Wait for me to say "continue."
- Before filtering, print the column names you plan to use and confirm they exist in the data. Do not guess column names.
- If anything looks off (weird counts, missing columns, rates that seem wrong), tell me instead of working around it.
- Keep code simple, commented, with a short header at the top of each script saying what it does. Teammates who are not strong coders need to read it.
- No em dashes anywhere in code comments, README, or the website text.

## Folder structure
```
fourth-down-caller/
  code/      Python scripts
  data/      data files (NOT committed to git, too large)
  docs/      website (GitHub Pages publishes from here)
  README.md
  .gitignore
```
Make sure `.gitignore` contains `data/`.

---

## Task 1: Setup
1. Create `code/`, `data/`, `docs/` if they don't exist.
2. Add `data/` to `.gitignore`.
3. Create `requirements.txt` with: nflreadpy, pandas, polars, pyarrow.
4. Install with `python3 -m pip install -r requirements.txt`.
5. Check: load one season (`nfl.load_pbp(2025)`) and print its shape.

## Task 2: Pull play-by-play (code/01_pull_pbp.py)
1. Load seasons 2018 through 2025.
2. Keep regular season only (`season_type == "REG"`).
3. Save to `data/pbp_2018_2025.parquet`.
4. Checks: total rows, rows per season, file size.

## Task 3: Filter the three play types (code/02_filter_plays.py)
Read the parquet from Task 2. Save three CSVs in `data/`.

**a) fourth_down_attempts.csv:** go-for-it plays.
- `down == 4` and `play_type` is `run` or `pass`. Exclude no-plays, kneels, and spikes.
- Keep: game_id, season, posteam, defteam, qtr, game_seconds_remaining, yardline_100, ydstogo, score_differential, wp, fourth_down_converted, fourth_down_failed.
- Checks: row count, overall conversion rate, and conversion rate by ydstogo for 1 through 10 (group 10+ together).

**b) field_goals.csv:** field goal attempts.
- `play_type == "field_goal"`.
- Keep: game_id, season, posteam, qtr, game_seconds_remaining, yardline_100, kick_distance, field_goal_result, score_differential, wp.
- Add a column `made` (1 if field_goal_result is "made", else 0).
- Checks: row count, make rate by 5-yard kick distance buckets.

**c) punts.csv:** punts.
- `play_type == "punt"`.
- Keep: game_id, season, posteam, qtr, game_seconds_remaining, yardline_100, kick_distance, return_yards, touchback, punt_blocked, score_differential.
- Add `net_punt_yards`: how far the field position actually moved, counting the return and the touchback. Explain in a comment exactly how you calculated it, and spot check 5 real punts by printing the play description (`desc`) next to your number.
- Checks: row count, mean and standard deviation of net_punt_yards, and a quick histogram saved as `data/net_punt_hist.png` so we can see if a normal distribution is reasonable.

## Task 4: Drive table (code/03_build_drives.py)
One row per drive. Use the `fixed_drive` and `fixed_drive_result` columns (confirm their exact names and values first and print the unique values of the result column).

Columns:
- game_id, season, posteam, defteam, fixed_drive
- start_yardline_100 (yardline_100 on the drive's first play)
- start_game_seconds_remaining, start_qtr
- start_score_differential (from posteam's view)
- drive_result (from fixed_drive_result)
- points_scored (by posteam on that drive)
- reached_fourth_down (1 if the drive had any fourth-down play)
- first_4th_yardline_100 and first_4th_ydstogo (the first fourth down the drive faced, blank if none)
- num_fourth_downs (how many fourth-down plays the drive had, to check how often a drive has more than one)

Save to `data/drives.csv`.

Checks: total drives, average drives per team per game, the share of each drive_result, and the share of drives with 2 or more fourth downs.

## Task 5: Website placeholder (docs/index.html)
1. A simple single page titled "4th Down Caller" with a one-line description: "A fourth-down decision tool built from a probabilistic dynamic program. Coming soon." Plain HTML and CSS in one file, nothing fancy.
2. Then tell me the manual steps I need to do on github.com to turn on GitHub Pages (Settings, Pages, deploy from the main branch, `/docs` folder) and to invite my teammates as collaborators.

## Task 6: README and push
1. Write `README.md` for teammates: what the project is, folder layout, how to install (`python3 -m pip install -r requirements.txt`), and the order to run the scripts (01, 02, 03). Note that `data/` is not on GitHub and is recreated by running the scripts, or downloaded from our shared Google Drive.
2. Commit with a clear message and push to GitHub.
3. Final summary for me: every file created, the key numbers from all the checks, and anything that looked strange.
