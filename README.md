# 4th Down Caller

IE 4520 (Stochastic Modeling) Group 4 class project.

We are building a probabilistic dynamic program that recommends the best NFL fourth-down call (go for it, kick a field goal, or punt) by picking the option that gives the highest chance of winning the game.

**Status:** the data is pulled and cleaned, the model inputs are built (`code/05_inputs.py`), the dynamic program is solved (`code/06_solve.py`), and the website is built (`code/08_website.py`). The model is described in `PLAN.md` and in "The model" below.

**Website:** https://dreznik68.github.io/fourth-down-caller/

## Folder layout

```
fourth-down-caller/
  code/              Python scripts (run them in number order)
  data/              data files (NOT on GitHub, see "Getting the data" below)
  outputs/           Excel workbook for the team (NOT on GitHub, shared in Google Drive)
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
- **openpyxl**: writes the Excel workbook
- **segno**: makes the QR code for the printable how-to

## Getting the data

The `data/` folder is not on GitHub because the files are too big (the main file is about 94 MB). There are two ways to get it:

1. **Recreate it** by running the three scripts below. Script 1 needs an internet connection.
2. **Download it** from our shared Google Drive folder and put the files in a folder named `data` inside the project folder.

## Running the scripts

From the project folder, run these in order:

| Order | Command | What it makes |
|---|---|---|
| 1 | `python3 code/01_pull_pbp.py` | `data/pbp_2018_2025.parquet` (every regular season play, 2018 to 2025) |
| 2 | `python3 code/02_filter_plays.py` | `data/fourth_down_attempts.csv`, `data/field_goals.csv`, `data/punts.csv`, `data/punt_distribution_by_bucket.csv`, `data/punt_mean_sd_by_bucket.csv`, `data/net_punt_hist.png` |
| 3 | `python3 code/03_build_drives.py` | `data/drives.csv` |
| 4 | `python3 code/04_team_outputs.py` | `outputs/Week1_Data_Summary.xlsx` (the team workbook) and `data/formula_checks.csv` |
| 5 | `python3 code/05_inputs.py` | `data/inputs/` (every input the dynamic program uses, see "The model" below) |
| 6 | `python3 code/06_solve.py` | `data/results/policy.csv` (best call for every situation) and `outputs/DP_Hand_Check.xlsx` |
| 7 | `python3 code/07_results.py` | `outputs/results/` (charts, comparison with real coaches, sensitivity tables) |
| 8 | `python3 code/08_website.py` | the data inside `docs/index.html`, the worked examples in `docs/instructions.html`, and `docs/qr.png` |

Scripts 2 and 3 read the file that script 1 makes, so run script 1 first. Scripts 4 and 5 read the files from scripts 2 and 3. Script 6 reads the files from script 5, and scripts 7 and 8 read the files from scripts 5 and 6. The model itself lives in `code/dp_model.py`, which scripts 6 and 7 both use, so the sensitivity runs use exactly the same model as the main solve. Each script prints checks (row counts, rates) when it finishes.

Script 4 also asks LibreOffice (installed in `/Applications`) to recalculate every formula in the workbook and compares each result with the same number computed in pandas. Without LibreOffice it still builds the workbook and skips that check.

## What is in each data file

| File | One row per | Rows |
|---|---|---|
| `pbp_2018_2025.parquet` | play (all 372 nflfastR columns) | 371,798 |
| `fourth_down_attempts.csv` | fourth-down run or pass (going for it) | 5,750 |
| `field_goals.csv` | field goal attempt | 8,241 |
| `punts.csv` | punt | 16,794 |
| `punt_distribution_by_bucket.csv` | start bucket and net yards bucket pair | 201 |
| `punt_mean_sd_by_bucket.csv` | start bucket | 13 |
| `drives.csv` | drive | 46,359 |

Data source: [nflfastR](https://www.nflfastr.com/) play-by-play, loaded with the [nflreadpy](https://github.com/nflverse/nflreadpy) Python package. Regular season games only.

The three play files also have `play_id` (to trace each play back to the play-by-play data) and `desc` (the text description of the play).

## The website

The tool is at https://dreznik68.github.io/fourth-down-caller/ (GitHub Pages publishes the `docs/` folder).

- `docs/index.html`: the tool, one self-contained page. Pick possessions left, score, field position, and yards to go. It shows the best call, the win probability of all three calls, a one-line "Why?", a decision tree (square = decision, circles = chance, win probability at each end), and the best call for every yards to go at that field position.
- `docs/instructions.html`: a one-page printable how-to with 3 worked examples and a QR code to the site.

The page does not run the model. `code/08_website.py` embeds the solved results: the best call for every situation, straight from `policy.csv`, and the win probability after each outcome (convert, fail, kick good, kick missed, punt). The page looks these up and multiplies by the outcome chances to draw the tree. Before writing, the script rebuilds every win probability the page will show and checks it against `policy.csv`. **Rerun scripts 6 and 8 whenever the model changes**, then commit `docs/`.


A dynamic program with one stage per possession left in the game (M, 1 to 8). We have the ball first and face a fourth down, so odd stages are ours and even stages are the opponent's. At each of our fourth downs it picks go, field goal, or punt to get the highest chance of winning. After the last possession, a win counts 1, a tie 0.5 (standing in for overtime), and a loss 0. The full model is in `PLAN.md`.

### Inputs (`code/05_inputs.py`, saved in `data/inputs/`)
- **c(t), conversion chance:** the raw conversion rate for each yards to go (1 to 9, and 10+), from the 5,512 real go-for-it attempts. We use the raw rates instead of a fitted curve because every group has 30 or more plays.
- **g(k), field goal chance:** the raw make rate for each 5-yard kick distance bucket, from all 8,241 kicks, like c(t). The groups are 15 to 24 yards (the 15 to 19 bucket had fewer than 30 kicks, so it is merged in, and it also covers any shorter kick), 25 to 29, ..., 55 to 59, and 60 to 64. A kick longer than 64 yards gets a 0% chance: only 19 have been tried (5 made), mostly by strong kickers in good conditions, so their rate would overstate a typical team's chance. Kick distance = yardline + 17.
- **P(y), punt distance:** the average net punt yards for each 5-yard start bucket.
- **D(y), how a drive ends:** the share of drives from each start bucket that end in a TD (+7), a FG (+3), or no score. The 3,136 "End of half" drives are left out, because the model handles the clock through M.
- **A, how our possession goes:** TD before any fourth down, FG before any fourth down (about 1%, almost all at the end of a half), no score before any fourth down, or the first fourth down at (y, t). One table for each start bucket, from the drives that started there, End of half drives left out. (Our possession can start anywhere now, because of H below. The table for S's bucket is the same as before.) One drive, 2018_13_IND_JAX drive 6, lists its first fourth down as 4th and 6 at the 1, which cannot happen, so it is used as 4th and goal.
- **S, start spot after a score (the kickoff):** 69.57 yards from the opponent's end zone, the 2024 and 2025 average. The 2024 kickoff rule change moved the average start 1.8 yards closer to the opponent than in 2018 to 2023, so we use the new seasons only. Rounded to 70 (your own 30).
- **H, start spot after a drive with no score (`H_handover.csv`):** for each start bucket, the average spot where the other team took over after drives from that bucket ended with no score. It comes from the next drive in the same game and half, from the other team's side of the field. There are two numbers per bucket: one for D's no-score drives (punts, turnovers, turnovers on downs, missed kicks), and one for A's no-score outcome (mostly turnovers). Groups with fewer than 30 drives are merged with their neighbor, and each average is rounded to the nearest yard, like S. For example, a no-score drive from your own 1 to 5 hands the other team the ball at about their 42, not their 30.
- **M guide:** the typical number of possessions left for each minute left in the 4th quarter. For example, about 5 with 10 minutes left, 3 with 5 minutes left, and 2 with 2 minutes left.

### Assumptions
- One fourth-down decision per possession (only 2.5% of drives have 2 or more).
- The opponent's calls, and our calls later in a drive, are league-typical.
- Punts use the average net distance for that spot.
- After a TD or FG, the other team starts at S. After a drive with no score, the other team starts at H for the bucket the drive started in. After one of our fourth-down calls, the call sets their start spot (failed go, missed kick, or punt).
- M is known.
- A converted fourth down that is not a TD carries on like a new drive from the spot it reached. A 10+ conversion gains exactly 10 yards.
- Defensive scores and safeties count as no score.
- Field position is in 5-yard buckets, and each bucket is worked out at its lowest yard (bucket 40 kicks from 57 yards).
- A punt that would carry past the goal line is a touchback at the 20. After a missed field goal the opponent starts at the spot of the kick or their own 20, whichever is better for them.

## Data notes

Nothing is deleted from the play files. Plays we leave out of an estimate are marked with a flag column (1 = yes, 0 = no), and the scripts filter on those flags when they estimate.

### fourth_down_attempts.csv (5,750 plays)
- Only plays that were a run or a pass on 4th down. Plays wiped out by a penalty (no-plays), kneels, and spikes are not in the file.
- `is_fake_kick` = 1 for **206** plays run from punt or field goal formation (fake punts and fake field goals).
- `is_botched_snap` = 1 for **51** plays nflfastR marked as aborted (a bad snap or a bad exchange). **19** plays have both flags.
- Conversion rates use the **5,512** plays with neither flag, because our "go for it" means the offense lining up to go for it. Fakes convert at a different rate (58.3% vs 53.8%) because of surprise.

### field_goals.csv (8,241 kicks)
- `on_fourth_down` = 0 for **724** kicks that were not on 4th down (mostly at the end of a half). One of these is a rare "fair catch kick" with no down.
- Make rates by distance use **all 8,241** kicks, because the kick itself does not depend on the down. Using 4th-down kicks only moves the overall make rate from 84.6% to 85.3%, and no 5-yard distance bucket moves by more than 1.4 percentage points.

### punts.csv (16,794 punts)
- `net_punt_yards` is how far the ball moved toward the receiving team's end zone:
  - touchback: `yardline_100 - 20`
  - blocked punt: where the ball actually ended up (see below)
  - every other punt: `kick_distance - return_yards`
  - Penalty yards are not counted.
- `has_penalty` = 1 for **1,471** punts with a penalty. **Left out** of the punt distribution, because penalty yards move the ball and our net does not count them.
- `is_muffed_recovered` = 1 for **124** punts where the returner muffed the punt and the punting team got the ball back. **Left out** of the distribution, because the punting team keeps the ball. We note this as a limitation.
- `is_fumble_recovered` = 1 for **52** punts where the returner caught the punt cleanly, then fumbled, and the punting team recovered. **Left out** for the same reason as recovered muffs.
- `return_team_scored` = 1 for **90** punts where the receiving team scored on the play: 83 touchdowns (punt returns and blocked punts returned for a score) and 7 safeties. **Left out**, because our model leaves out defensive scores.
- `punting_team_scored` = 1 for **9** punts where the punting team scored on the play: 6 touchdowns after recovering a muff or fumble, and 3 safeties when the returner was downed in his own end zone. **Left out** for the same reason.
- `is_blocked` = 1 for **91** blocked punts. **Kept in** the distribution, because a block is a real outcome of choosing to punt. nflfastR records 0 kick yards and 0 return yards for every blocked punt, so `net_punt_yards` uses where the ball ended up instead:
  - **58**: the spot where the receiving team took over (their next snap)
  - **33**: the defense scored a touchdown or safety, so the ball ended in the punting team's end zone (`net_punt_yards = yardline_100 - 100`). These are also flagged `return_team_scored`, so they are left out.
  - **56** blocked punts are in the distribution after all exclusions.
- A punt can have more than one flag. **1,734** punts have at least one exclusion flag, so the punt distribution uses **15,060** punts.

### punt_distribution_by_bucket.csv and punt_mean_sd_by_bucket.csv
- Buckets are 5 yards wide and named by their lowest value. `start_bucket` 40 means the punt started at yardline_100 40 to 44. `net_yards_bucket` -5 means -5 to -1 net yards.
- `start_bucket` 35 holds every punt from yardline_100 **39 or less** (238 punts). Buckets 25 and 30 had too few punts to stand on their own, so they are merged into 35.
- In each `start_bucket`, the `probability` column adds up to 1.
- We use these per-bucket distributions instead of one normal curve, because net punt yards change a lot with field position. The mean is about 26 yards when punting from the opponent's 39 or closer, but about 43 to 44 yards from your own side of the field. The SD is about 6 to 7 yards near midfield and about 10 yards deep in your own end.

### drives.csv (46,359 drives)
- A drive starts at its first snap, not the kickoff.
- **392** drive numbers with no snap at all are left out. These include **53 kickoff-return touchdowns** (the receiving team scored before running a play). Most of the rest are game-start and end-of-game marker rows, or kickoffs right before halftime.
- **4** drives are dropped because nflfastR put two different offenses under one drive number: 2018_01_TEN_MIA drive 13, 2018_09_CHI_BUF drive 21, 2019_02_TB_CAR drive 2, and 2023_12_PIT_CIN drive 8. Two of these (CHI_BUF and TB_CAR) are also the 2 field goal drives that showed 0 points, so 4 drives are dropped in total.
- Fourth-down plays wiped out by a penalty are not counted in `num_fourth_downs`. **1,143** drives (2.5%) had 2 or more fourth downs that stood.

### Season coverage
- 2022 has 271 regular season games instead of 272, because the Bills at Bengals game in Week 17 was canceled after Damar Hamlin's cardiac arrest.
