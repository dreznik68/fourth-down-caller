"""
07_results.py

What this script does:
    Turns the solved policy into results for the report, saved in outputs/results/:
        1. Charts of the best call by field position and yards to go for three
           common cases (PNG, plus the same grid as a CSV):
               tied with M = 4, down 3 with M = 2, up 3 with M = 2
        2. How often the model's best call matched what real coaches did on
           4th downs in the 4th quarter, by field position bucket
        3. Sensitivity: how many states change their best call if the
           conversion chance moves 10 points, the opponent's TD chance moves
           10 points, or M is off by 1
        4. A check on pooling c(t): conversion rate in our own half vs the
           opponent's half for t = 1 to 5
    Every table is saved as a CSV, and a short summary is printed at the end.

How to run (from the project root folder):
    python3 code/07_results.py

Needs:
    data/results/policy.csv (run 06_solve.py first), data/inputs/,
    data/fourth_down_attempts.csv, data/field_goals.csv, data/punts.csv,
    data/pbp_2018_2025.parquet (for yards to go on punts and field goals)
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save charts to files instead of opening a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from dp_model import load_inputs, policy_table, solve

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = PROJECT_ROOT / "outputs" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

KEY = ["M", "d", "y", "t"]
CASES = [  # (file name, M, d, chart title)
    ("tied_M4", 4, 0, "Tied, 4 possessions left"),
    ("down3_M2", 2, -3, "Down 3, 2 possessions left"),
    ("up3_M2", 2, 3, "Up 3, 2 possessions left"),
]
CLOSE_CALL = 0.01   # best call wins by less than 1 point of win probability
SHIFT = 0.10        # sensitivity: move a probability by 10 points

# Chart colors: the first three categorical slots (validated as a set), a
# neutral gray for "any", and recessive ink for text and axes.
COLORS = {"go": "#2a78d6", "fg": "#eb6834", "punt": "#1baf7a", "any": "#c3c2b7"}
LABELS = {"go": "Go for it", "fg": "Field goal", "punt": "Punt", "any": "Any (game decided)"}
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
plt.rcParams["font.family"] = ["Arial", "Helvetica", "DejaVu Sans"]

policy = pd.read_csv(DATA_DIR / "results" / "policy.csv")


def bucket(values):
    """Round each yardline down to the start of its 5-yard bucket (43 -> 40)."""
    return (np.floor(np.asarray(values, dtype=float) / 5) * 5).astype(int)


def field_label(y):
    """Plain-English name of a field position bucket, like 'Opp 40-44' or 'Own 46-50'."""
    if y + 4 < 50:
        return f"Opp {max(y, 1)}-{y + 4}"
    return f"Own {100 - (y + 4)}-{100 - y}"


# ===============================================================
# 1. Charts: best call by field position and yards to go
# ===============================================================
def draw_case(name, M, d, title):
    """Heatmap of the best call. x = field position (we drive left to right),
    y = yards to go. A white dot marks a close call."""
    sub = policy[(policy["M"] == M) & (policy["d"] == d)]
    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for r in sub.itertuples():
        left = 100 - r.y - 5   # bucket y covers yardline_100 y to y + 4
        # A thin edge in the surface color leaves a small gap between cells.
        ax.add_patch(Rectangle((left, r.t - 0.5), 5, 1, facecolor=COLORS[r.best],
                               edgecolor=SURFACE, linewidth=0.75))
        if r.margin < CLOSE_CALL and r.best != "any":
            ax.plot(left + 2.5, r.t, "o", ms=2.6, color="white")

    ax.set_xlim(0, 100)
    ax.set_ylim(0.5, 10.5)
    ax.set_xticks(range(0, 101, 10))
    ax.set_xticklabels(["Own goal", "Own 10", "Own 20", "Own 30", "Own 40", "50",
                        "Opp 40", "Opp 30", "Opp 20", "Opp 10", "Opp goal"])
    ax.set_yticks(range(1, 11))
    ax.set_yticklabels([str(t) for t in range(1, 10)] + ["10+"])
    ax.set_xlabel("Field position (your offense drives left to right)", color=INK2, fontsize=10)
    ax.set_ylabel("Yards to go", color=INK2, fontsize=10)
    ax.tick_params(colors=MUTED, labelcolor=INK2, labelsize=9, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    present = [c for c in ["go", "fg", "punt", "any"] if c in set(sub["best"])]
    handles = [Patch(facecolor=COLORS[c], label=LABELS[c]) for c in present]
    handles.append(Line2D([], [], marker="o", linestyle="", markersize=5, color=INK2,
                          label="Close call (within 1 point)"))
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=len(handles),
              frameon=False, fontsize=9, labelcolor=INK2, handlelength=1.2, borderaxespad=0)
    fig.text(0.01, 0.97, f"Best fourth-down call: {title}", fontsize=13, fontweight="bold",
             color=INK, va="top")
    fig.text(0.01, 0.915, "Call with the highest win probability from the dynamic program. "
             "Blank cells cannot happen (more yards to go than yards to the goal line).",
             fontsize=9, color=INK2, va="top")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(OUT_DIR / f"best_call_{name}.png", facecolor=SURFACE)
    plt.close(fig)

    # The same grid as a table: rows = yards to go, columns = field position.
    grid = sub.pivot(index="t", columns="y", values="best").sort_index(axis=1, ascending=False)
    grid.columns = [field_label(y) for y in grid.columns]
    grid.index = [str(t) if t < 10 else "10+" for t in grid.index]
    grid.index.name = "yards_to_go"
    grid.to_csv(OUT_DIR / f"best_call_{name}.csv")
    return sub["best"].value_counts(normalize=True)


case_shares = {name: draw_case(name, M, d, title) for name, M, d, title in CASES}

# ===============================================================
# 2. Compare with real coaches: 4th downs in the 4th quarter
# ===============================================================
# Coach's call:
#   go   = a real go-for-it play. Fake punts and fake field goals count as go
#          (the coach chose to go for it). Botched snaps are left out, because
#          we cannot tell what the coach meant to do.
#   fg   = a field goal attempt on 4th down
#   punt = a punt on 4th down
# Yards to go for punts and field goals comes from the play-by-play file.
# M for each play is what a user would read off the M guide: the average
# number of possessions left at the nearest whole minute, rounded, 1 to 8.
pbp = pd.read_parquet(DATA_DIR / "pbp_2018_2025.parquet", columns=["game_id", "play_id", "down", "ydstogo"])
cols = ["game_id", "play_id", "qtr", "game_seconds_remaining", "yardline_100", "score_differential"]

go = pd.read_csv(DATA_DIR / "fourth_down_attempts.csv")
go = go[go["is_botched_snap"] == 0][cols + ["ydstogo"]].assign(coach="go")
fg = pd.read_csv(DATA_DIR / "field_goals.csv")
fg = fg[fg["on_fourth_down"] == 1][cols].merge(pbp, on=["game_id", "play_id"]).assign(coach="fg")
punt = pd.read_csv(DATA_DIR / "punts.csv")[cols].merge(pbp, on=["game_id", "play_id"])
punt = punt[punt["down"] == 4].assign(coach="punt")
real = pd.concat([go, fg.drop(columns="down"), punt.drop(columns="down")], ignore_index=True)
real = real[real["qtr"] == 4]
n_q4 = len(real)

guide = pd.read_csv(DATA_DIR / "inputs" / "M_guide.csv").set_index("minutes_left")["mean_M"]
minute = np.clip(np.floor(real["game_seconds_remaining"] / 60 + 0.5), 1, 15).astype(int)
real["M"] = np.clip(np.floor(guide.loc[minute].to_numpy() + 0.5), 1, 8).astype(int)
real["d"] = real["score_differential"].astype(int)
real["y"] = bucket(real["yardline_100"])
real["t"] = real["ydstogo"].clip(upper=10).astype(int)

real = real[real["d"].abs() <= 21]
n_in_range = len(real)
real = real.merge(policy[KEY + ["best", "margin"]], on=KEY, how="left")
assert real["best"].notna().all(), "every real play should match a policy state"
n_any = int((real["best"] == "any").sum())
real = real[real["best"] != "any"].copy()
real["match"] = (real["best"] == real["coach"]).astype(int)

by_field = real.groupby("y").agg(
    plays=("match", "size"), matches=("match", "sum"), match_rate=("match", "mean"),
    coach_go_share=("coach", lambda s: (s == "go").mean()),
    model_go_share=("best", lambda s: (s == "go").mean()),
).reset_index().sort_values("y", ascending=False)
by_field.insert(1, "field_position", by_field["y"].map(field_label))
by_field = by_field.rename(columns={"y": "y_bucket"})
by_field.round(4).to_csv(OUT_DIR / "coach_match_by_field_position.csv", index=False)

coach_vs_model = pd.crosstab(real["coach"], real["best"], margins=True, margins_name="total")
coach_vs_model.index.name = "coach_call \\ model_call"
coach_vs_model.to_csv(OUT_DIR / "coach_vs_model.csv")

clear = real["margin"] >= 0.02

# ===============================================================
# 3. Sensitivity: how many states change their best call
# ===============================================================
# A state only counts if the call matters in both versions (best is not "any").
base_inp = load_inputs()


def best_calls(inp, m_max=8):
    """Solve with these inputs and return the best call for every (M, d, y, t)."""
    d_vals, F, _ = solve(inp, m_max)
    return policy_table(d_vals, F).set_index(KEY)["best"]


def changes(base, other):
    """Per M: states where both calls matter, and how many of those differ."""
    both = pd.concat([base.rename("a"), other.rename("b")], axis=1, join="inner")
    both = both[(both["a"] != "any") & (both["b"] != "any")]
    by_m = both.groupby(level="M").apply(lambda g: pd.Series(
        {"states": len(g), "changed": int((g["a"] != g["b"]).sum())}))
    return by_m


def change_table(base, plus, minus, labels):
    """One small table: rows M = 1 to 8 (plus a total), columns for each direction."""
    parts = []
    for label, other in zip(labels, [plus, minus]):
        c = changes(base, other).reindex(range(1, 9))
        c.columns = [f"{label}_states", f"{label}_changed"]
        c[f"{label}_pct"] = c[f"{label}_changed"] / c[f"{label}_states"]
        parts.append(c)
    table = pd.concat(parts, axis=1)
    total = table.sum(numeric_only=True)
    for label in labels:
        total[f"{label}_pct"] = total[f"{label}_changed"] / total[f"{label}_states"]
    table.loc["all"] = total
    table.index.name = "M"
    for col in table.columns:
        if not col.endswith("_pct"):
            table[col] = table[col].astype("Int64")  # whole numbers (blank allowed for M = 1)
    return table


base = best_calls(base_inp, m_max=9)   # M = 9 only for the "M + 1" comparison at M = 8
base8 = base[base.index.get_level_values("M") <= 8]
assert (base8.sort_index().to_numpy() == policy.set_index(KEY)["best"].sort_index().to_numpy()).all(), \
    "the sensitivity base must match policy.csv"


def with_conversion(change):
    inp = load_inputs()
    inp["c"] = {t: float(np.clip(p + change, 0, 1)) for t, p in inp["c"].items()}
    return best_calls(inp)


def with_opponent_td(change):
    """Move the opponent's TD chance by `change` in every start bucket. The
    no-score chance takes up the difference; their FG chance stays the same."""
    inp = load_inputs()
    inp["opp_td"] = np.clip(inp["opp_td"] + change, 0, 1 - inp["opp_fg"])
    return best_calls(inp)


conv_plus, conv_minus = with_conversion(SHIFT), with_conversion(-SHIFT)
opp_plus, opp_minus = with_opponent_td(SHIFT), with_opponent_td(-SHIFT)


def shift_M(series, by):
    """Relabel M so state (M, d, y, t) lines up with (M + by, d, y, t)."""
    idx = series.index.to_frame(index=False)
    idx["M"] = idx["M"] - by
    out = series.copy()
    out.index = pd.MultiIndex.from_frame(idx)
    return out[(out.index.get_level_values("M") >= 1) & (out.index.get_level_values("M") <= 8)]


sens = {
    "sensitivity_conversion": change_table(base8, conv_plus, conv_minus, ["plus10", "minus10"]),
    "sensitivity_opponent_td": change_table(base8, opp_plus, opp_minus, ["plus10", "minus10"]),
    "sensitivity_M": change_table(base8, shift_M(base, 1), shift_M(base, -1), ["M_plus1", "M_minus1"]),
}
for name, table in sens.items():
    table.round(4).to_csv(OUT_DIR / f"{name}.csv")


def go_share(series):
    s = series[series != "any"]
    return (s == "go").mean()


# ===============================================================
# 4. Does pooling c(t) make the model too aggressive?
# ===============================================================
# Conversion rate in our own half (yardline_100 over 50) vs the opponent's
# half (50 or closer), for t = 1 to 5, on the same plays as c(t).
att = pd.read_csv(DATA_DIR / "fourth_down_attempts.csv")
att = att[(att["is_fake_kick"] == 0) & (att["is_botched_snap"] == 0) & (att["ydstogo"] <= 5)].copy()
att["half"] = np.where(att["yardline_100"] > 50, "own", "opp")
pooled = base_inp["c"]
att["pooled_c"] = att["ydstogo"].map(pooled)

half_table = att.pivot_table(index="ydstogo", columns="half", values="fourth_down_converted",
                             aggfunc=["size", "mean"])
half_table.columns = [f"{h}_half_{'attempts' if s == 'size' else 'rate'}" for s, h in half_table.columns]
half_table = half_table[["own_half_attempts", "own_half_rate", "opp_half_attempts", "opp_half_rate"]]
half_table["pooled_c"] = [pooled[t] for t in half_table.index]
half_table["own_minus_pooled"] = half_table["own_half_rate"] - half_table["pooled_c"]
half_table.index.name = "t"
half_table.round(4).to_csv(OUT_DIR / "conversion_by_half.csv")

own = att[att["half"] == "own"]
own_actual, own_expected = own["fourth_down_converted"].mean(), own["pooled_c"].mean()

# ===============================================================
# Summary
# ===============================================================
print("========== Summary ==========")
print("1. Charts (best call share of all states in each chart):")
for name, M, d, title in CASES:
    shares = ", ".join(f"{c} {p:.0%}" for c, p in case_shares[name].items())
    print(f"   {title}: {shares}  -> best_call_{name}.png")

print(f"\n2. Real coaches, 4th quarter 4th downs: {n_q4:,} plays, {n_in_range:,} with score "
      f"within 21, {n_any:,} left out because the game was decided (any call), "
      f"{len(real):,} compared.")
print(f"   Model matched the coach on {real['match'].mean():.1%}. "
      f"Coaches went for it {(real['coach'] == 'go').mean():.1%} of the time, "
      f"the model says go {(real['best'] == 'go').mean():.1%}.")
print(f"   When the model's call is clear (wins by 2+ points, {clear.sum():,} plays): match "
      f"{real.loc[clear, 'match'].mean():.1%}. Close calls ({(~clear).sum():,} plays): "
      f"{real.loc[~clear, 'match'].mean():.1%}.")
print("   Coach call (rows) vs model call (columns):")
print("   " + coach_vs_model.to_string().replace("\n", "\n   "))
print("   By field position:")
show = by_field[["field_position", "plays", "match_rate", "coach_go_share", "model_go_share"]]
print("   " + show.round(3).to_string(index=False).replace("\n", "\n   "))

print("\n3. Sensitivity (states where the call matters in both; share that change their best call):")
for name, table in sens.items():
    a, b = [c[:-4] for c in table.columns if c.endswith("_pct")]
    row = table.loc["all"]
    print(f"   {name}: {a} {int(row[a + '_changed']):,} of {int(row[a + '_states']):,} "
          f"({row[a + '_pct']:.1%}), {b} {int(row[b + '_changed']):,} of {int(row[b + '_states']):,} "
          f"({row[b + '_pct']:.1%})")
print(f"   Go share of states: base {go_share(base8):.1%}, conversion +10 {go_share(conv_plus):.1%}, "
      f"-10 {go_share(conv_minus):.1%}, opponent TD +10 {go_share(opp_plus):.1%}, "
      f"-10 {go_share(opp_minus):.1%}")

print(f"\n4. Pooling c(t): in our own half, t = 1 to 5 plays converted {own_actual:.1%} vs "
      f"{own_expected:.1%} predicted by pooled c(t) ({own_actual - own_expected:+.1%}, "
      f"{len(own):,} plays). See conversion_by_half.csv.")
print(half_table.round(3).to_string())
print(f"\nAll tables and charts saved to: {OUT_DIR}")
