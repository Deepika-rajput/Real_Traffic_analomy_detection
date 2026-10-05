import torch
from torch.utils.data import Dataset

from .config import CLIP_LEN, NORMAL


class WindowDataset(Dataset):
    """Sliding CLIP_LEN windows over cached per-segment feature sequences.

    features/<split>.pt = {"seqs": [ (n_i, 527) ... ], "labels": [int ...], "names": [str ...]}
    A window never crosses a segment boundary, so labels stay clean.
    hop        : step between windows for normal segments
    anomaly_hop: step for anomaly segments (use 1 to squeeze the most out of rare events)
    """

    def __init__(self, path, hop=4, anomaly_hop=None, train=False):
        d = torch.load(path)
        self.seqs, self.labels, self.names = d["seqs"], d["labels"], d["names"]
        self.train = train
        self.index, ys = [], []
        for si, s in enumerate(self.seqs):
            h = hop if (self.labels[si] == NORMAL or anomaly_hop is None) else anomaly_hop
            for st in range(0, len(s) - CLIP_LEN + 1, h):
                self.index.append((si, st))
                ys.append(self.labels[si])
        self.y = torch.tensor(ys, dtype=torch.long)

    def __len__(self):
        return len(self.index)

    def __getitem__(self, i):
        si, st = self.index[i]
        x = self.seqs[si][st: st + CLIP_LEN]
        if self.train:
            x = x + 0.05 * x.std() * torch.randn_like(x)            # feature noise
            if torch.rand(1).item() < 0.5:                           # temporal jitter
                x = x.clone()
                for t in torch.randint(1, x.size(0), (2,)).tolist():
                    x[t] = x[t - 1]
        return x, self.y[i]
