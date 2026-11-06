# PLAN.md: Simplified Model + All Remaining Tasks

This replaces MODEL_SPEC.md. If MODEL_SPEC.md is in the project root, delete it.

Rules: stop after each task, show the checks, wait for "continue." Commit after each task. No em dashes anywhere. Keep code short and commented. Use the existing cleaned data and flags in `data/`.

## The model (keep it exactly this simple)

**Stages:** n = 1, ..., M, one stage per possession left in the game. Possessions alternate and we have the ball first, so odd stages are ours and even stages are the opponent's. M is a user input (1 to 8). We give a data table of typical M by minutes left so the user can pick it.

**States:**
- Our stage: s_n = (d, y, t) when we face fourth down. d = our score minus theirs, y = yardline_100 (5-yard bucket), t = yards to go (1 to 9, 10+).
- Opponent stage: s_n = (d, y_opp), where y_opp is their start spot.

**Decision variable:** x_n in {go, fg, punt} in our stages. No decision in opponent stages; their outcome comes from data.

**Decision benefit function:**
f_n(s_n, x_n) = sum over s_(n+1) of p_s(n+1)(x_n) * f*_(n+1)(s_(n+1))
f*_n(s_n) = max over x_n of f_n(s_n, x_n); x*_n is the call that gives it.

**Boundary condition:** f*_(M+1)(d) = 1 if d > 0, 0.5 if d = 0, 0 if d < 0.

**What each call does (from our fourth down at y, t):**
- go: convert with prob c(t). Converted: TD if t = y, otherwise the rest of the drive follows D(y - t). Failed: opponent starts at 100 - y.
- fg: make with prob g(y + 17). Made: d + 3, opponent starts at the average start spot S. Missed: opponent starts at min(100 - (y + 7), 80).
- punt: opponent starts at 100 - (y - P(y)), where P(y) is the average net punt for that start bucket.

**Chance pieces:**
- D(y): a drive starting at y ends in TD (+7), FG (+3), or no score. From drives.csv by start bucket. Used for opponent possessions and for the rest of our drive after a conversion.
- A: our possession starting at S. Outcomes: TD before any fourth down, no score before any fourth down, or fourth down at (y, t). From drives.csv using drives that start in S's bucket.
- S: average start spot for a new possession (kickoffs and possessions after a no-score drive). One number from drives.csv. Kickoff rules changed in 2024, so if 2024 and 2025 differ, use those seasons and tell me.
- After any score or no-score drive end, the other team starts at S.

**Assumptions to list in the README:** one fourth-down decision per possession (only 2.5% of drives have 2 or more), opponent and later drive calls are league-typical, punts use the average net distance for that spot, new possessions start at S, M is known.

---

## Task 8: Inputs (code/05_inputs.py) -> data/inputs/
Save: `c_conversion.csv` (logistic fit on ydstogo, raw vs fitted shown), `g_fieldgoal.csv` (logistic fit on kick distance, raw vs fitted by 5-yard bucket), `P_punt.csv` (mean net punt by start bucket, already computed), `D_drive.csv` (P(TD), P(FG), P(none) by start bucket), `A_our_possession.csv`, `S_start.txt`, `M_guide.csv` (mean, SD, and most common M by minute left in Q4).
Checks: each probability table sums to 1, counts per group (flag under 30), the M guide at 10, 5, and 2 minutes left.

## Task 9: Solver + hand check (code/06_solve.py)
1. Solve for M = 1 to 8 and every (d, y, t) with d from -21 to +21. Save `data/results/policy.csv`: M, d, y, t, f for go, fg, punt, and the best call.
2. Hand check: M = 1, d = -3, y = 40, 35, 30, t = 1, 2, 5. With M = 1 there is no stage after ours, so:
   f_1(go) = c(t) * (P_TD + 0.5 * P_FG) from D(y - t), f_1(fg) = 0.5 * g(y + 17), f_1(punt) = 0.
   Build `outputs/DP_Hand_Check.xlsx`: an Inputs tab with the probabilities used, and a Table tab in the professor's format (rows s_1; columns f_1(s_1, go), f_1(s_1, fg), f_1(s_1, punt), f*_1, x*_1). Every Table cell is a live formula from Inputs. Recalculate with LibreOffice and confirm it matches the solver exactly.
3. Sanity checks: down 3 with M = 1, punt = 0; up 10 with M = 1, all calls near 1; fourth and 1 at the opponent's 2, down 4, M = 1, go beats fg. Report any failure.

## Task 10: Results + sensitivity (code/07_results.py) -> outputs/results/
1. Charts (PNG) for the report: best call by field position and yards to go for 3 common cases (tied with M = 4, down 3 with M = 2, up 3 with M = 2).
2. Compare to real coaches: for real fourth downs in Q4, how often our best call matched what the coach did, by field position bucket.
3. Sensitivity: rerun with conversion prob +/- 10 points, opponent TD prob +/- 10 points, and M +/- 1. One small table per change showing how many states change their best call.
4. Save every table as CSV and print a short summary.

## Task 11: Website (docs/)
1. `docs/index.html`, one self-contained page, results embedded as JSON from policy.csv (no live model).
2. Inputs as dropdowns: possessions left (show the M guide next to it, like "about 5 possessions with 8 minutes left"), score differential, field position, yards to go.
3. Output on the first screen: recommended call in large text, win prob for all three calls, a small probability tree for the recommended call, and a one-line "Why?" built from simple rules (for example, if the field goal still leaves you behind, say so).
4. Low friction: 3 "Try this" buttons with preset situations, works on a phone, no sign-up, loads instantly.
5. `docs/instructions.html`: a one-page printable how-to with 3 worked examples, plus a QR code image to the site URL https://dreznik68.github.io/fourth-down-caller/.
6. Commit. Then tell me to push and check the site loads.
