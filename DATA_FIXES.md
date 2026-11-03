# Data Fixes (answers to your 9 flagged items)

Apply these, rerun the affected scripts, then show me the updated key numbers. Same rules as before: stop when done, no em dashes. Do not delete rows silently. Add flag columns so every exclusion is traceable, and filter on the flags when estimating.

1. **Fake kicks and botched snaps:** Keep them in fourth_down_attempts.csv, but add `is_fake_kick` and `is_botched_snap` columns (1/0). Exclude both from the conversion rate estimates. Our "go for it" means the offense lining up to go for it, and fakes convert at a biased rate because of surprise.

2. **Net punt yards:** Add `has_penalty`, `is_blocked`, and `is_muffed_recovered` flags. Exclude penalty punts from the punt distribution. Keep blocked punts in, since they are a real outcome of choosing to punt. Exclude muffs the punting team recovered (rare, we will note it as a limitation).

3. **Punt distribution:** Drop the single normal curve. Instead, build the empirical distribution of net punt yards for each 5-yard bucket of starting field position (yardline_100), using the same buckets as the rest of the model. Save it as `data/punt_distribution_by_bucket.csv` with columns: start_bucket, net_yards_bucket, count, probability. Probabilities in each start_bucket must sum to 1. Also save the mean and SD per start bucket so we can show in the report why one normal curve did not fit.

4. **Field goals not on 4th down:** Keep them and add an `on_fourth_down` flag. Use all kicks for the make rate by distance, since the kick itself does not depend on the down. Report the make rate both ways so I can confirm it barely changes.

5. **392 no-snap drives:** Leaving them out is fine. Mention the 53 kickoff-return touchdowns in the README notes as a known exclusion.

6. **Penalty-wiped fourth downs:** Do not count them. Keep "drives with 2 or more fourth downs" based on plays that stood (1,145 drives, 2.5%).

7. **Data errors:** Drop the 4 merged drives and the 2 FG drives showing 0 points. Print their game_id and fixed_drive so I can list them in the report.

8. **2022 canceled game:** No action. Add one line to the README notes.

9. **matplotlib:** Fine, keep it.

After this, add a short "Data notes" section at the bottom of README.md that lists every exclusion and flag above in plain English with the row counts. Then commit (I will push), and move on to TASK7_TEAM_OUTPUTS.md if it is in the project root. Update Task 7's Punt Distance tab to show the per-bucket table and the mean and SD by start bucket instead of the single normal comparison.
