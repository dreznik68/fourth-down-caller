"""
dp_model.py

What this file does:
    The fourth-down dynamic program from PLAN.md, written as functions so that
    06_solve.py (the main solve) and 07_results.py (the sensitivity runs) use
    exactly the same model. Running this file on its own does nothing; the
    scripts import it.

The model, in the solver's terms:
    k = possessions left in the game, counting the current one (k = M at the
        4th down we are deciding). Ours and theirs alternate.
    d = our score minus theirs. f*(d) at the end = 1 if d > 0, 0.5 if d = 0, 0 if d < 0.
    Three value tables, each a win probability:
        W[k](d)       our possession starts at S, k possessions left
        O[k](d, y)    their possession starts in bucket y, k possessions left
        F[k](d, y, t) we face 4th down at y with t to go, k possessions left
    W uses A (how our possession from S goes), O uses D (how their drive goes),
    and F tries go, fg, and punt, each leading to their possession O[k - 1].

Field position:
    y is the 5-yard bucket name (40 means yardline_100 40 to 44). The formulas
    use the bucket's lowest yard as the exact yardline, so y = 40 kicks from
    57 yards. If t is larger than that (only possible inside the 10, for
    example 4th and goal from the 3 is bucket 0), the yardline is t, which
    makes it 4th and goal.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

IN_DIR = Path(__file__).resolve().parent.parent / "data" / "inputs"

CALLS = ["go", "fg", "punt"]
D_OUT = 21                      # policy covers d from -21 to +21
N_BUCKETS = 20                  # field position buckets 0, 5, ..., 95
FG_EXTRA_YARDS = 17             # kick distance = yardline + 17
MISSED_FG_BACK = 7              # a missed kick gives the ball back 7 yards behind the line
MISSED_FG_MAX = 80              # ...but never worse for them than their own 20
TOUCHBACK = 80                  # a punt into the end zone gives them the ball at their 20

# Policy states: every bucket y and yards to go t that can happen there
# (t can be at most the bucket's highest yard, so bucket 0 only has t = 1 to 4).
GRID = [(y, t) for y in range(0, 100, 5) for t in range(1, 11) if t <= y + 4]


def bi(yardline):
    """Bucket index (0 to 19) of a yardline: 1 to 4 -> 0, 40 to 44 -> 8."""
    return min(int(yardline // 5), N_BUCKETS - 1)


def shift(v, s):
    """v at d + s for every d (clamped at the edges, where the game is decided)."""
    return v[np.clip(np.arange(len(v)) + s, 0, len(v) - 1)]


def load_inputs():
    """Read data/inputs into a dict. Probabilities are recomputed from the
    counts so they are exact (the CSVs show rounded values)."""
    c_df = pd.read_csv(IN_DIR / "c_conversion.csv")
    g_fit = pd.read_csv(IN_DIR / "logistic_fits.csv").set_index("fit").loc["g_fieldgoal"]
    p_df = pd.read_csv(IN_DIR / "P_punt.csv")
    d_df = pd.read_csv(IN_DIR / "D_drive.csv").set_index("start_bucket").sort_index()
    assert list(d_df.index) == list(range(0, 100, 5)), "D_drive.csv must have buckets 0 to 95"
    a_df = pd.read_csv(IN_DIR / "A_our_possession.csv")
    a_df["p"] = a_df["drives"] / a_df["drives"].sum()
    s_info = dict(line.strip().split("=") for line in open(IN_DIR / "S_start.txt")
                  if "=" in line and not line.startswith("#"))

    d_td = (d_df["td_drives"] / d_df["drives"]).to_numpy()
    d_fg = (d_df["fg_drives"] / d_df["drives"]).to_numpy()
    cells = a_df.loc[a_df["outcome"] == "fourth_down", ["y", "t", "p"]]
    inp = {
        "c": dict(zip(c_df["t"], c_df["conversions"] / c_df["attempts"])),
        "g_a": g_fit["intercept_a"], "g_b": g_fit["slope_b"],
        "punt": dict(zip(p_df["start_bucket"], p_df["mean_net_yards"])),
        # D for the rest of OUR drive after a conversion...
        "d_td": d_td, "d_fg": d_fg,
        # ...and D for THEIR drives (the same data, kept separate so a
        # sensitivity run can change one without the other)
        "opp_td": d_td.copy(), "opp_fg": d_fg.copy(),
        "a_td": a_df.loc[a_df["outcome"] == "td", "p"].sum(),
        "a_fg": a_df.loc[a_df["outcome"] == "fg", "p"].sum(),
        "a_none": a_df.loc[a_df["outcome"] == "none", "p"].sum(),
        "a_cells": [(int(y), int(t), p) for y, t, p in cells.itertuples(index=False)],
        "s_bucket": int(s_info["S_bucket"]),
    }
    assert all((y, t) in GRID for y, t, _ in inp["a_cells"]), "every A cell must be a policy state"
    return inp


def g(inp, kick_distance):
    """Field goal make chance from the logistic fit."""
    return 1 / (1 + math.exp(-(inp["g_a"] + inp["g_b"] * kick_distance)))


def their_possession(inp, W_next):
    """O[k](d, y) for every start bucket: their drive ends in TD (-7), FG (-3),
    or no score, then we start at S with one fewer possession left (W_next)."""
    td, fg = inp["opp_td"], inp["opp_fg"]
    return (td[None, :] * shift(W_next, -7)[:, None]
            + fg[None, :] * shift(W_next, -3)[:, None]
            + (1 - td - fg)[None, :] * W_next[:, None])


def call_values(inp, O_next, yardline, t):
    """Win probability of go, fg, and punt (3 rows) from 4th and t at an exact
    yardline. O_next[d, b] = win probability when they get the ball in bucket b next."""
    at_S = O_next[:, bi(inp["s_bucket"])]  # they start at S (after any score by us)
    c = inp["c"][t]

    # go: convert with prob c(t). Converted: TD if t = yardline, otherwise the
    # rest of the drive follows D(yardline - t). Failed: they start at 100 - y.
    if t >= yardline:
        converted = shift(at_S, 7)
    else:
        b = bi(yardline - t)
        td, fg = inp["d_td"][b], inp["d_fg"][b]
        converted = td * shift(at_S, 7) + fg * shift(at_S, 3) + (1 - td - fg) * at_S
    failed = O_next[:, bi(100 - yardline)]
    go = c * converted + (1 - c) * failed

    # fg: make with prob g(y + 17) and they start at S. Missed: they start at
    # the spot of the kick (y + 7 from their goal), or their 20 if that is better.
    make = g(inp, yardline + FG_EXTRA_YARDS)
    missed_spot = max(min(100 - (yardline + MISSED_FG_BACK), MISSED_FG_MAX), 1)
    fg = make * shift(at_S, 3) + (1 - make) * O_next[:, bi(missed_spot)]

    # punt: the ball moves P(y) yards (punts from inside the 40 use bucket 35).
    # If that would carry past the goal line, it is a touchback at their 20.
    ball = yardline - inp["punt"][min(max(bi(yardline) * 5, 35), 95)]
    their_start = TOUCHBACK if ball < 1 else 100 - ball
    punt = O_next[:, bi(their_start)]
    return np.vstack([go, fg, punt])


def solve(inp, m_max=8):
    """Backward recursion over possessions left, k = 1 to m_max.
    Returns d_vals (the score differences), F, and O, where
    F[(k, y, t)] is a 3 x len(d_vals) array (go, fg, punt) and O[k] is the
    win probability when they get the ball with k possessions left."""
    # Scores move by at most 7 per possession, so d from -21 to +21 needs room
    # for m_max more possessions. Outside this range the game is already decided.
    d_lim = D_OUT + 7 * m_max
    d_vals = np.arange(-d_lim, d_lim + 1)
    terminal = np.where(d_vals > 0, 1.0, np.where(d_vals == 0, 0.5, 0.0))
    bs = bi(inp["s_bucket"])

    W = [terminal]                                    # W[0]: game over
    O = [np.tile(terminal[:, None], (1, N_BUCKETS))]  # O[0]: game over
    F = {}
    for k in range(1, m_max + 1):
        best = {}
        for y, t in GRID:
            F[(k, y, t)] = call_values(inp, O[k - 1], max(y, t), t)
            best[(y, t)] = F[(k, y, t)].max(axis=0)
        at_S = O[k - 1][:, bs]
        W.append(inp["a_td"] * shift(at_S, 7) + inp["a_fg"] * shift(at_S, 3)
                 + inp["a_none"] * at_S
                 + sum(p * best[(y, t)] for y, t, p in inp["a_cells"]))
        O.append(their_possession(inp, W[k - 1]))
    return d_vals, F, O


def policy_table(d_vals, F):
    """One row per (M, d, y, t) with d from -D_OUT to +D_OUT: the win
    probability of each call, the best call ("any" if all three are exactly
    equal, meaning the game is already decided), and its margin over the next best."""
    keep = np.abs(d_vals) <= D_OUT
    blocks = []
    for (k, y, t), vals in F.items():
        v = np.round(vals[:, keep], 12)        # round so exact ties count as ties
        order = np.sort(v, axis=0)
        best = np.where(order[-1] == order[0], "any", np.array(CALLS)[v.argmax(axis=0)])
        blocks.append(pd.DataFrame({
            "M": k, "d": d_vals[keep], "y": y, "t": t, "yardline": max(y, t),
            "f_go": v[0], "f_fg": v[1], "f_punt": v[2],
            "best": best,
            "margin": order[-1] - order[-2],    # best minus second best
        }))
    return pd.concat(blocks).sort_values(["M", "d", "y", "t"]).reset_index(drop=True)
