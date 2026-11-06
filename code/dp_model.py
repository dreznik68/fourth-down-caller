"""
dp_model.py

What this file does:
    The fourth-down dynamic program from PLAN.md, written as functions so that
    06_solve.py (the main solve), 07_results.py (the sensitivity runs), and
    08_website.py use exactly the same model. Running this file on its own
    does nothing; the scripts import it.

The model, in the solver's terms:
    k = possessions left in the game, counting the current one (k = M at the
        4th down we are deciding). Ours and theirs alternate.
    d = our score minus theirs. f*(d) at the end = 1 if d > 0, 0.5 if d = 0, 0 if d < 0.
    Three value tables, each a win probability:
        W[k](d, b)    our possession starts in bucket b, k possessions left
        O[k](d, b)    their possession starts in bucket b, k possessions left
        F[k](d, y, t) we face 4th down at y with t to go, k possessions left
    W uses A (how our possession from bucket b goes), O uses D (how their
    drive goes), and F tries go, fg, and punt, each leading to their
    possession O[k - 1].

Where the next possession starts:
    After a TD or FG, the other team starts at S (the kickoff spot).
    After a drive with no score, the other team starts at H, the average spot
    where drives from that start bucket actually handed over the ball
    (H_handover.csv). D's no-score outcome uses d_start; A's uses a_start.
    After one of our 4th-down calls, the call itself sets their start spot.

Field position:
    y is the 5-yard bucket name (40 means yardline_100 40 to 44). The formulas
    use the bucket's lowest yard as the exact yardline, so y = 40 kicks from
    57 yards. If t is larger than that (only possible inside the 10, for
    example 4th and goal from the 3 is bucket 0), the yardline is t, which
    makes it 4th and goal.
"""

from pathlib import Path

import numpy as np
import pandas as pd

IN_DIR = Path(__file__).resolve().parent.parent / "data" / "inputs"

CALLS = ["go", "fg", "punt"]
D_OUT = 21                      # policy covers d from -21 to +21
N_BUCKETS = 20                  # field position buckets 0, 5, ..., 95
BUCKETS = list(range(0, 100, 5))
FG_EXTRA_YARDS = 17             # kick distance = yardline + 17
MISSED_FG_BACK = 7              # a missed kick gives the ball back 7 yards behind the line
MISSED_FG_MAX = 80              # ...but never worse for them than their own 20
TOUCHBACK = 80                  # a punt into the end zone gives them the ball at their 20

# Policy states: every bucket y and yards to go t that can happen there
# (t can be at most the bucket's highest yard, so bucket 0 only has t = 1 to 4).
GRID = [(y, t) for y in BUCKETS for t in range(1, 11) if t <= y + 4]


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
    g_df = pd.read_csv(IN_DIR / "g_fieldgoal.csv").sort_values("kick_min")
    p_df = pd.read_csv(IN_DIR / "P_punt.csv")
    d_df = pd.read_csv(IN_DIR / "D_drive.csv").set_index("start_bucket").sort_index()
    h_df = pd.read_csv(IN_DIR / "H_handover.csv").set_index("start_bucket").sort_index()
    a_df = pd.read_csv(IN_DIR / "A_our_possession.csv")
    for df in (d_df, h_df):
        assert list(df.index) == BUCKETS, "D and H need every bucket from 0 to 95"
    a_df["p"] = a_df["drives"] / a_df.groupby("start_bucket")["drives"].transform("sum")
    s_info = dict(line.strip().split("=") for line in open(IN_DIR / "S_start.txt")
                  if "=" in line and not line.startswith("#"))

    def a_share(outcome):
        """Chance of an A outcome, for each start bucket."""
        rows = a_df[a_df["outcome"] == outcome].groupby("start_bucket")["p"].sum()
        return rows.reindex(BUCKETS, fill_value=0).to_numpy()

    cells = a_df[a_df["outcome"] == "fourth_down"]
    d_td = (d_df["td_drives"] / d_df["drives"]).to_numpy()
    d_fg = (d_df["fg_drives"] / d_df["drives"]).to_numpy()
    inp = {
        "c": dict(zip(c_df["t"], c_df["conversions"] / c_df["attempts"])),
        # (longest kick in the group, make rate), shortest group first
        "g": list(zip(g_df["kick_max"], g_df["makes"] / g_df["attempts"])),
        "punt": dict(zip(p_df["start_bucket"], p_df["mean_net_yards"])),
        # D for the rest of OUR drive after a conversion...
        "d_td": d_td, "d_fg": d_fg,
        # ...and D for THEIR drives (the same data, kept separate so a
        # sensitivity run can change one without the other)
        "opp_td": d_td.copy(), "opp_fg": d_fg.copy(),
        # A for each start bucket: chances of TD, FG, or no score before any
        # 4th down, and the (y, t, chance) of the first 4th down
        "a_td": a_share("td"), "a_fg": a_share("fg"), "a_none": a_share("none"),
        "a_cells": [[(int(y), int(t), p) for y, t, p in
                     cells.loc[cells["start_bucket"] == b, ["y", "t", "p"]].itertuples(index=False)]
                    for b in BUCKETS],
        # H: bucket index where the other team starts after a no-score drive
        "h_d": np.array([bi(x) for x in h_df["d_start"]]),
        "h_a": np.array([bi(x) for x in h_df["a_start"]]),
        "s_bucket": int(s_info["S_bucket"]),
    }
    assert all((y, t) in GRID for b in inp["a_cells"] for y, t, _ in b), "every A cell must be a policy state"
    return inp


def g(inp, kick_distance):
    """Field goal make chance: the raw make rate of the kick's distance group.
    The shortest group also covers any shorter kick. A kick longer than the
    longest group (the 64-yard cap) gets 0."""
    for kick_max, rate in inp["g"]:
        if kick_distance <= kick_max:
            return rate
    return 0.0


def their_possession(inp, W_next):
    """O[k](d, b) for every start bucket b: their drive ends in TD (-7) or FG
    (-3) and we start at S, or ends with no score and we start at H (d_start)
    for their bucket. W_next is our win probability with one fewer possession left."""
    td, fg, bs = inp["opp_td"], inp["opp_fg"], bi(inp["s_bucket"])
    return (td[None, :] * shift(W_next[:, bs], -7)[:, None]
            + fg[None, :] * shift(W_next[:, bs], -3)[:, None]
            + (1 - td - fg)[None, :] * W_next[:, inp["h_d"]])


def converted_value(inp, O_next, b):
    """Win probability after we convert and the drive goes on from bucket b:
    D says TD (+7) or FG (+3), and they start at S, or no score, and they
    start at H (d_start) for bucket b."""
    at_S = O_next[:, bi(inp["s_bucket"])]
    td, fg = inp["d_td"][b], inp["d_fg"][b]
    return td * shift(at_S, 7) + fg * shift(at_S, 3) + (1 - td - fg) * O_next[:, inp["h_d"][b]]


def call_values(inp, O_next, yardline, t):
    """Win probability of go, fg, and punt (3 rows) from 4th and t at an exact
    yardline. O_next[d, b] = win probability when they get the ball in bucket b next."""
    at_S = O_next[:, bi(inp["s_bucket"])]  # they start at S (after any score by us)
    c = inp["c"][t]

    # go: convert with prob c(t). Converted: TD if t = yardline, otherwise the
    # rest of the drive follows D(yardline - t). Failed: they start at 100 - y.
    converted = shift(at_S, 7) if t >= yardline else converted_value(inp, O_next, bi(yardline - t))
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

    W = [np.tile(terminal[:, None], (1, N_BUCKETS))]  # W[0]: game over
    O = [np.tile(terminal[:, None], (1, N_BUCKETS))]  # O[0]: game over
    F = {}
    for k in range(1, m_max + 1):
        best = {}
        for y, t in GRID:
            F[(k, y, t)] = call_values(inp, O[k - 1], max(y, t), t)
            best[(y, t)] = F[(k, y, t)].max(axis=0)
        at_S = O[k - 1][:, bs]
        # Our possession from each start bucket b: TD or FG before a 4th down
        # (they start at S), no score before a 4th down (they start at H,
        # a_start), or our first 4th down at (y, t), where we make the best call.
        W.append(np.column_stack([
            inp["a_td"][b] * shift(at_S, 7) + inp["a_fg"][b] * shift(at_S, 3)
            + inp["a_none"][b] * O[k - 1][:, inp["h_a"][b]]
            + sum(p * best[(y, t)] for y, t, p in inp["a_cells"][b])
            for b in range(N_BUCKETS)]))
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
