"""Alert rule in vectorised form (used to simulate the live detector during evaluation)."""
import numpy as np


def rolling_alerts(hit, k, n):
    """hit: bool array per prediction. Alert is active when >= k of the last n predictions hit."""
    hit = np.asarray(hit, dtype=int)
    roll = np.convolve(hit, np.ones(n, dtype=int))[: len(hit)]
    return roll >= k


def onsets(active):
    active = np.asarray(active, dtype=bool)
    prev = np.r_[False, active[:-1]]
    return active & ~prev
