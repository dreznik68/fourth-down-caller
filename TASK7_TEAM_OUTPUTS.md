# Task 7: Clean Outputs for Teammates

Do this after Task 6. Same rules as CLAUDE_CODE_TASKS.md: stop when done, show me the checks, no em dashes anywhere.

## Why
I write all the code. My teammates (Aidan, Charlie, John) are not coders and will never open the scripts. They work only from what is in `outputs/`, which I share in our Google Drive. Everything here has to make sense to someone who only opens Excel.

## Setup
- Create an `outputs/` folder and add `outputs/` to `.gitignore` (shared through Google Drive, not GitHub).
- Add `openpyxl` to `requirements.txt`.
- Write the script as `code/04_team_outputs.py` so I can rerun it whenever the data changes.

## Deliverable: outputs/Week1_Data_Summary.xlsx

**Excel rules (important):**
- Every summary number must be a live Excel formula that traces back to the raw data tabs (COUNTIFS, AVERAGEIFS, AVERAGE, STDEV.S, etc.). No pasted values in summary tabs.
- No double counting. Each play appears in exactly one raw tab row.
- Font Arial 11, bold headers, freeze the top row on every tab, column widths that fit the text, numbers formatted (percentages as %, yards to 1 decimal).
- After writing, recalculate the workbook (for example with LibreOffice headless) and confirm every formula result matches the same number computed in pandas. Report any mismatch.

**Tabs, in this order:**

1. **How To Use**: one short paragraph on what the workbook is, then a list of every tab with one line on what it shows and which teammate it is mainly for. Note the data source (nflfastR, 2018 to 2025 regular season) and the date it was built.

2. **Column Guide**: every column in the raw tabs with a plain-English meaning (for example, "yardline_100: yards from the opponent's end zone, so 1 means the 1-yard line and 99 means your own 1"). Also explain how net_punt_yards was calculated.

3. **Conversion by Yards**: yards to go 1 through 9 plus 10+, with columns for attempts, conversions, and conversion rate. Formulas pull from the 4th down raw tab. Add a line chart of conversion rate vs yards to go.

4. **FG by Distance**: 5-yard kick distance buckets with attempts, makes, and make rate. Formulas pull from the FG raw tab. Add a line chart.

5. **Punt Distance**: count, mean, standard deviation, min, max, and median of net_punt_yards as formulas. A bucket table (5-yard bins) with counts for a histogram, plus a column chart of it. Next to it, a column with the count a normal distribution with the same mean and SD would predict for each bin (NORM.DIST formulas), so Aidan can compare the two and judge the normal assumption.

6. **Drive Results**: count and share of each drive_result, average drives per team per game, and the share of drives with 2 or more fourth downs. All formulas from the drives raw tab.

7. **Raw_4thDown**, **Raw_FG**, **Raw_Punts**, **Raw_Drives**: the cleaned data from Tasks 3 and 4, only the columns listed there plus `desc` (the play description) so teammates can read what happened on any play.

If any raw tab would push the file past about 50 MB, tell me before cutting anything.

## Checks to show me
- File size and row count of each raw tab
- The key numbers from every summary tab, side by side with the pandas versions
- A screenshot-style description of each chart (what is on each axis)
- Anything that looked off
