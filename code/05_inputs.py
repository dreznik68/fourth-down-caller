"""
05_inputs.py

What this script does:
    Builds every input the dynamic program needs (see PLAN.md) and saves them
    in data/inputs/:
        c_conversion.csv     c(t): chance of converting a 4th down with t yards to go
                             (the raw conversion rate, since every group has 30+ plays)
        g_fieldgoal.csv      g(k): chance of making a field goal of k yards (the raw
                             make rate by 5-yard distance bucket, small buckets merged)
        P_punt.csv           P(y): mean net punt yards by start bucket
        D_drive.csv          D(y): chance a drive starting at y ends in TD, FG, or no score
        A_our_possession.csv A: how our possession starting in each bucket ends (TD, FG,
                             or no score before any 4th down, or the first 4th down at (y, t))
        H_handover.csv       where the other team starts after a drive with no score,
                             by the bucket the drive started in
        S_start.txt          S: average start spot for a new possession
        M_guide.csv          typical number of possessions left (M) by minutes left in Q4
    It prints checks: each probability table sums to 1, counts per group
    (groups under 30 are flagged), and the M guide at 10, 5, and 2 minutes left.

How to run (from the project root folder):
    python3 code/05_inputs.py

Needs:
    data/fourth_down_attempts.csv, data/field_goals.csv,
    data/punt_mean_sd_by_bucket.csv (from 02_filter_plays.py)
    data/drives.csv (from 03_build_drives.py)

Notation:
    y = yardline_100 (yards from the opponent's end zone), in 5-yard buckets
        named by their lowest value: bucket 40 means yardline_100 40 to 44.
    t = yards to go, 1 to 9, and 10 means "10 or more".
"""

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = DATA_DIR / "inputs"
OUT_DIR.mkdir(exist_ok=True)

BUCKET_SIZE = 5    # yards per field position bucket
T_MAX = 10         # yards to go of 10 or more go in one group, t = 10
MIN_COUNT = 30     # groups with fewer plays or drives than this are flagged
G_MAX_KICK = 64    # longest field goal the model will try; anything longer has g = 0

# Kickoff rules changed in 2024. If the average start spot in 2024 and 2025
# differs from 2018 to 2023 by at least this many yards, S uses 2024 and 2025 only.
NEW_KICKOFF_SEASONS = [2024, 2025]
S_CHANGE_YARDS = 1.0


def bucket(values):
    """Round each yardline down to the start of its 5-yard bucket (43 -> 40)."""
    return (np.floor(np.asarray(values, dtype=float) / BUCKET_SIZE) * BUCKET_SIZE).astype(int)


def flag_small(df, count_col):
    """Add low_count = 1 for groups with fewer than MIN_COUNT plays or drives."""
    df["low_count"] = (df[count_col] < MIN_COUNT).astype(int)
    return df


def merge_small(counts):
    """Group neighboring buckets so each group has at least MIN_COUNT items.
    counts is indexed by bucket, smallest first. Buckets are added to a group
    until it is big enough, then a new group starts. A short group left over
    at the end joins the one before it. Returns a list of lists of buckets."""
    groups, current = [], []
    for b in counts.index:
        current.append(b)
        if counts.loc[current].sum() >= MIN_COUNT:
            groups.append(current)
            current = []
    if current:
        if groups:
            groups[-1] += current
        else:
            groups.append(current)
    return groups


def print_flags(df, name, key_cols):
    """Print which groups (if any) are under MIN_COUNT."""
    small = df[df["low_count"] == 1]
    if len(small) == 0:
        print(f"  All {name} groups have {MIN_COUNT} or more.")
    else:
        print(f"  FLAG: {len(small)} {name} group(s) under {MIN_COUNT}: "
              f"{small[key_cols].to_dict('records')}")


# ===============================================================
# c(t): conversion chance by yards to go
# ===============================================================
# Plays used: real go-for-it attempts (not fake kicks, not botched snaps),
# the same plays as the conversion rates in 02_filter_plays.py.
# c(t) is the raw conversion rate for each t. Every group has 30+ plays, so no
# smoothing fit is needed. In the model a 10+ conversion gains exactly 10 yards.
go = pd.read_csv(DATA_DIR / "fourth_down_attempts.csv")
go = go[(go["is_fake_kick"] == 0) & (go["is_botched_snap"] == 0)].copy()
go["t"] = go["ydstogo"].clip(upper=T_MAX)

c_table = go.groupby("t").agg(
    attempts=("fourth_down_converted", "size"),
    conversions=("fourth_down_converted", "sum"),
    conversion_rate=("fourth_down_converted", "mean"),
).reset_index()
c_table = flag_small(c_table, "attempts")
c_table.round(6).to_csv(OUT_DIR / "c_conversion.csv", index=False)

print("========== c_conversion.csv (t = 10 means 10 or more) ==========")
print(f"Plays used: {len(go):,}")
print(c_table.round(3).to_string(index=False))
print_flags(c_table, "yards to go", ["t", "attempts"])

# ===============================================================
# g(k): field goal make chance by kick distance
# ===============================================================
# Uses all kicks (the kick does not depend on the down), as in 02_filter_plays.py.
# The model asks for g(y + 17): the ball is snapped 7 yards behind the line of
# scrimmage and the goal posts are 10 yards behind the goal line.
#
# g(k) is the raw make rate of k's 5-yard distance bucket, like c(t). A bucket
# with fewer than 30 kicks is merged into its neighbor toward the middle (the
# 15 bucket joins 20). Kicks longer than G_MAX_KICK get g = 0: only a few have
# ever been tried (by strong kickers in good conditions), so their make rate
# would overstate a typical team's chance. They are left out of the table.
fg_all = pd.read_csv(DATA_DIR / "field_goals.csv")
fg = fg_all[fg_all["kick_distance"] <= G_MAX_KICK].copy()
fg["distance_bucket"] = bucket(fg["kick_distance"])
counts = fg.groupby("distance_bucket")["made"].agg(["size", "sum"])


def kicks_in(group):
    """Number of kicks in a group of 5-yard buckets."""
    return counts.loc[group, "size"].sum()


groups = merge_small(counts["size"])          # each group is a list of 5-yard buckets

g_table = pd.DataFrame([{
    "kick_min": gr[0],
    "kick_max": gr[-1] + BUCKET_SIZE - 1,
    "attempts": int(kicks_in(gr)),
    "makes": int(counts.loc[gr, "sum"].sum()),
} for i, gr in enumerate(groups)])
g_table["make_rate"] = g_table["makes"] / g_table["attempts"]
g_table = flag_small(g_table, "attempts")
g_table.round(6).to_csv(OUT_DIR / "g_fieldgoal.csv", index=False)

print("\n========== g_fieldgoal.csv ==========")
over = fg_all[fg_all["kick_distance"] > G_MAX_KICK]
print(f"Kicks used: {len(fg):,}. The first group also covers any shorter kick. "
      f"g = 0 beyond {G_MAX_KICK} yards ({len(over)} longer kicks left out, "
      f"{int(over['made'].sum())} made).")
print(g_table.round(3).to_string(index=False))
print_flags(g_table, "distance", ["kick_min", "attempts"])

# ===============================================================
# P(y): mean net punt yards by start bucket
# ===============================================================
# Already computed in 02_filter_plays.py. Start bucket 35 holds every punt from
# yardline_100 39 or less, so the solver uses bucket 35 for any y under 40.
p_table = pd.read_csv(DATA_DIR / "punt_mean_sd_by_bucket.csv")
p_table = flag_small(p_table, "punts")
p_table.to_csv(OUT_DIR / "P_punt.csv", index=False)

print("\n========== P_punt.csv ==========")
print(p_table.to_string(index=False))
print_flags(p_table, "punt start", ["start_bucket", "punts"])

# ===============================================================
# S: average start spot for a new possession
# ===============================================================
# Every drive in drives.csv starts either after a kickoff or after the other
# team's drive ended with no score, so S is the average start over all drives.
# The model works in whole yards, so S is rounded to the nearest yard before
# finding its bucket.
drives = pd.read_csv(DATA_DIR / "drives.csv")
by_season = drives.groupby("season")["start_yardline_100"].mean()
new_rules = drives["season"].isin(NEW_KICKOFF_SEASONS)
old_mean = drives.loc[~new_rules, "start_yardline_100"].mean()
new_mean = drives.loc[new_rules, "start_yardline_100"].mean()

use_new = abs(new_mean - old_mean) >= S_CHANGE_YARDS
s_drives = drives[new_rules] if use_new else drives
S_mean = s_drives["start_yardline_100"].mean()
S_yard = int(round(S_mean))
S_bucket = int(bucket([S_yard])[0])
seasons_used = f"{s_drives['season'].min()} to {s_drives['season'].max()}"

with open(OUT_DIR / "S_start.txt", "w") as f:
    f.write("# S = average start spot (yardline_100) for a new possession, from drives.csv\n")
    f.write(f"# Seasons used: {seasons_used} ({len(s_drives):,} drives)\n")
    f.write(f"S_mean={S_mean:.2f}\n")
    f.write(f"S_yardline={S_yard}\n")
    f.write(f"S_bucket={S_bucket}\n")

print("\n========== S_start.txt ==========")
print("Average start yardline_100 by season (all drives):")
print(by_season.round(2).to_string())
print(f"2018 to 2023: {old_mean:.2f}, 2024 to 2025: {new_mean:.2f}, "
      f"difference {new_mean - old_mean:+.2f} yards")
print(f"Use 2024 and 2025 only: {use_new} (rule: difference of {S_CHANGE_YARDS} yard or more)")
print(f"S = {S_mean:.2f} -> rounded to yardline_100 {S_yard} (own {100 - S_yard}), "
      f"bucket {S_bucket} ({len(s_drives):,} drives, {seasons_used})")

# ===============================================================
# D(y): how a drive starting at y ends
# ===============================================================
# TD (+7) if drive_result is Touchdown, FG (+3) if Field goal, otherwise no score.
# Defensive scores (Opp touchdown, Safety) count as no score, since the model
# leaves out defensive scores. All seasons are used: how a drive ends from a
# given spot does not depend on the kickoff rules.
#
# Drives that ended because the half or game ran out ("End of half") are left
# out of D and A. Most started in the last 2 minutes of a half (many are
# kneel downs after an onside kick). The model handles the clock through M,
# the number of possessions left, so a drive in the model always plays out.
drives["start_bucket"] = bucket(drives["start_yardline_100"])
drives["is_td"] = (drives["drive_result"] == "Touchdown").astype(int)
drives["is_fg"] = (drives["drive_result"] == "Field goal").astype(int)
end_of_half = drives["drive_result"] == "End of half"
played_out = drives[~end_of_half]

d_table = played_out.groupby("start_bucket").agg(
    drives=("is_td", "size"), td_drives=("is_td", "sum"), fg_drives=("is_fg", "sum"),
).reset_index()
d_table["p_td"] = d_table["td_drives"] / d_table["drives"]
d_table["p_fg"] = d_table["fg_drives"] / d_table["drives"]
d_table["p_none"] = 1 - d_table["p_td"] - d_table["p_fg"]
d_table = flag_small(d_table, "drives")
d_table.round(6).to_csv(OUT_DIR / "D_drive.csv", index=False)

print("\n========== D_drive.csv ==========")
print(f"End of half drives left out: {int(end_of_half.sum()):,} of {len(drives):,}. "
      f"Drives used: {len(played_out):,}")
print(d_table.drop(columns=["td_drives", "fg_drives"]).round(3).to_string(index=False))
row_sums = d_table[["p_td", "p_fg", "p_none"]].sum(axis=1)
print(f"  Every row sums to 1: {bool(np.allclose(row_sums, 1))}")
print_flags(d_table, "start", ["start_bucket", "drives"])

# ===============================================================
# A: how our possession starting in each bucket ends
# ===============================================================
# Drives that start in each bucket (End of half drives left out, as in D).
# The model used to need A only at S. Now a drive with no score hands the
# other team the ball where such drives usually end (see H below), so we
# need our possession from any start bucket. A at S's bucket is unchanged.
# Each drive ends in exactly one of:
#   td:          touchdown before any 4th down
#   fg:          field goal before any 4th down (a kick on 1st to 3rd down,
#                almost always at the end of a half)
#   none:        no score before any 4th down (turnover, defensive score,
#                missed kick on 1st to 3rd down)
#   fourth_down: the drive reached a 4th down. y and t are where the FIRST
#                4th down was, whatever happened after it.
a = played_out.copy()
reached = a["reached_fourth_down"] == 1
a["outcome"] = np.select(
    [reached, a["is_td"] == 1, a["is_fg"] == 1],
    ["fourth_down", "td", "fg"],
    default="none",
)
# Yards to go can never be more than the yards to the goal line. One drive
# breaks this (printed below), so t is capped at the yardline (4th and goal).
impossible = a[reached & (a["first_4th_ydstogo"] > a["first_4th_yardline_100"])]
a["y"] = np.where(reached, bucket(a["first_4th_yardline_100"].fillna(0)), np.nan)
a["t"] = np.where(reached, np.minimum(a["first_4th_ydstogo"], a["first_4th_yardline_100"]).clip(upper=T_MAX),
                  np.nan)

a_table = (a.groupby(["start_bucket", "outcome", "y", "t"], dropna=False).size()
           .rename("drives").reset_index())
a_table["probability"] = a_table["drives"] / a_table.groupby("start_bucket")["drives"].transform("sum")
order = {"td": 0, "fg": 1, "none": 2, "fourth_down": 3}
a_table = a_table.sort_values(["start_bucket", "outcome", "y", "t"],
                              key=lambda s: s.map(order) if s.name == "outcome" else s)
a_table["y"] = a_table["y"].astype("Int64")
a_table["t"] = a_table["t"].astype("Int64")
a_table = flag_small(a_table, "drives")
a_table.round(6).to_csv(OUT_DIR / "A_our_possession.csv", index=False)

print("\n========== A_our_possession.csv (one table per start bucket) ==========")
print(f"Drives used: {len(a):,} (all seasons)")
for r in impossible.itertuples():
    print(f"  Fixed: {r.game_id} drive {r.fixed_drive} lists its first 4th down as 4th and "
          f"{r.first_4th_ydstogo:.0f} at the {r.first_4th_yardline_100:.0f}. Used as 4th and goal.")
shares = a_table.pivot_table(index="start_bucket", columns="outcome", values="probability",
                             aggfunc="sum").fillna(0)[["td", "fg", "none", "fourth_down"]]
shares.insert(0, "drives", a.groupby("start_bucket").size())
print(shares.round(3).to_string())
sums = a_table.groupby("start_bucket")["probability"].sum()
print(f"  Probabilities sum to 1 in every start bucket: {bool(np.allclose(sums, 1))}")
s_rows = a_table[a_table["start_bucket"] == S_bucket]
small = s_rows[(s_rows["outcome"] == "fourth_down") & (s_rows["low_count"] == 1)]
print(f"  At S's bucket ({S_bucket}): {len(s_rows) - 3} fourth_down (y, t) cells, {len(small)} under "
      f"{MIN_COUNT} drives, holding {small['probability'].sum():.3f} of the probability")

# ===============================================================
# H: where the other team starts after a drive with no score
# ===============================================================
# The handover of a drive is the next drive in the same game and the same
# half, if the other team ran it. Its start_yardline_100 is where the other
# team took over, from their side of the field. Drives with no handover
# (the other team scored on a return, the half ended, or the game ended) are
# left out of the averages.
#   d_start: after any no-score drive from the bucket (punts, turnovers,
#            turnovers on downs, missed kicks). Used for D: their drives,
#            and the rest of our drive after a conversion.
#   a_start: after the no-score drives that ended before any 4th down
#            (mostly turnovers). Used for A's "none" outcome.
# A group with fewer than 30 drives is merged into its neighbor, like the kick
# distance buckets, so every bucket still gets one number. The model rounds
# each average to the nearest yard, like S.
drives = drives.sort_values(["game_id", "fixed_drive"]).reset_index(drop=True)
nxt = drives.groupby("game_id")[["posteam", "start_yardline_100", "start_qtr"]].shift(-1)


def half(qtr):
    """1 = first half, 2 = second half, 3 = overtime."""
    return np.select([qtr <= 2, qtr <= 4], [1, 2], default=3)


drives["handover"] = ((nxt["posteam"] == drives["defteam"])
                      & (half(drives["start_qtr"]) == half(nxt["start_qtr"].fillna(0))))
drives["next_start"] = nxt["start_yardline_100"]
no_score = drives[(drives["drive_result"] != "End of half") & (drives["is_td"] == 0)
                  & (drives["is_fg"] == 0) & drives["handover"]]
all_buckets = list(range(0, 100, BUCKET_SIZE))

h_table = pd.DataFrame({"start_bucket": all_buckets})
for name, rows in [("d", no_score), ("a", no_score[no_score["reached_fourth_down"] == 0])]:
    grouped = rows.groupby("start_bucket")["next_start"].agg(["size", "sum"]).reindex(all_buckets, fill_value=0)
    for group in merge_small(grouped["size"]):
        n, total = grouped.loc[group, "size"].sum(), grouped.loc[group, "sum"].sum()
        at = h_table["start_bucket"].isin(group)
        h_table.loc[at, f"{name}_group"] = f"{group[0]} to {group[-1] + BUCKET_SIZE - 1}"
        h_table.loc[at, f"{name}_drives"] = n
        h_table.loc[at, f"{name}_mean"] = total / n
    h_table[f"{name}_start"] = np.floor(h_table[f"{name}_mean"] + 0.5).astype(int)
    h_table[f"{name}_drives"] = h_table[f"{name}_drives"].astype(int)
h_table.round(2).to_csv(OUT_DIR / "H_handover.csv", index=False)

print("\n========== H_handover.csv ==========")
print(f"No-score drives with a handover: {len(no_score):,}. Without H, every one of them "
      f"would give the other team the ball at S = {S_yard}.")
print(h_table.round(1).to_string(index=False))
assert (h_table[["d_drives", "a_drives"]] >= MIN_COUNT).all().all(), "a handover group has under 30 drives"
print(f"  Every group has {MIN_COUNT} or more drives.")

# ===============================================================
# M guide: possessions left by minutes left in Q4
# ===============================================================
# At each whole minute left in the game (15 down to 1), for every game:
#   M = 1 (the possession in progress) + the number of drives that start later.
# Only regulation drives count (start_qtr 1 to 4); a tie after M possessions is
# worth 0.5 in the model, which stands in for overtime.
regulation = drives[drives["start_qtr"] <= 4]
all_games = regulation["game_id"].unique()
guide_rows = []
for minutes in range(15, 0, -1):
    later = regulation[regulation["start_game_seconds_remaining"] < 60 * minutes]
    M = 1 + later.groupby("game_id").size().reindex(all_games, fill_value=0)
    guide_rows.append({
        "minutes_left": minutes, "games": len(M), "mean_M": M.mean(), "sd_M": M.std(),
        "most_common_M": int(M.mode().min()), "share_over_8": (M > 8).mean(),
    })
m_guide = flag_small(pd.DataFrame(guide_rows), "games")
m_guide.round(3).to_csv(OUT_DIR / "M_guide.csv", index=False)

print("\n========== M_guide.csv ==========")
print(m_guide.round(2).to_string(index=False))
for minutes in [10, 5, 2]:
    r = m_guide[m_guide["minutes_left"] == minutes].iloc[0]
    print(f"  {minutes:>2} minutes left: mean M {r['mean_M']:.2f}, SD {r['sd_M']:.2f}, "
          f"most common {int(r['most_common_M'])}")

print(f"\nAll inputs saved to: {OUT_DIR}")
