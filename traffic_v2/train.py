"""Train the temporal transformer on cached features (4 traffic states).

    python make_labels.py
    python extract_features.py
    python train.py

Saves temporal.pth = best weights (by val macro-F1) + one alert threshold per anomaly class.
Prints window-level AND event-level results (event-level simulates the real alert rule:
did it alert on each event, how fast, and how many false alerts per hour on normal footage).
"""
import os

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler

from src.alerts import onsets, rolling_alerts
from src.config import (ALERT_RULE, ANOMALIES, CLASSES, CLIP_LEN, INFER_EVERY, NORMAL,
                        SAMPLE_FPS)
from src.dataset import WindowDataset
from src.model import TemporalTransformer

EPOCHS = 40
PATIENCE = 8
BATCH = 32
LR = 3e-4
TRAIN_HOP, TRAIN_ANOMALY_HOP, EVAL_HOP = 4, 1, 8
TARGET_PRECISION = 0.95      # per-class alert threshold = lowest one that keeps this precision on val
MIN_WINDOWS = 50             # warn if a class has fewer train windows than this
MIN_VAL_WINDOWS = 30         # below this a class's val metrics/threshold are too noisy to trust
DEFAULT_THR = 0.80

torch.manual_seed(0)
np.random.seed(0)
torch.set_num_threads(os.cpu_count() or 4)


@torch.no_grad()
def predict(model, ds):
    model.eval()
    ps, ys = [], []
    for x, y in DataLoader(ds, batch_size=64):
        ps.append(torch.softmax(model(x), 1))
        ys.append(y)
    return torch.cat(ps).numpy(), torch.cat(ys).numpy()


def prf(pred_pos, true_pos):
    tp = int((pred_pos & true_pos).sum())
    fp = int((pred_pos & ~true_pos).sum())
    fn = int((~pred_pos & true_pos).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


@torch.no_grad()
def event_eval(model, path, thresholds, title):
    """Run the real alert rule (threshold + k-of-N) over every segment, in time order."""
    model.eval()
    d = torch.load(path)
    stats = {c: {"n": 0, "hit": 0, "lat": []} for c in ANOMALIES}
    normal_h, false_alerts = 0.0, 0
    for s, lab in zip(d["seqs"], d["labels"]):
        if len(s) < CLIP_LEN:
            continue
        starts = list(range(0, len(s) - CLIP_LEN + 1, INFER_EVERY))
        probs = []
        for i in range(0, len(starts), 256):
            x = torch.stack([s[a:a + CLIP_LEN] for a in starts[i:i + 256]])
            probs.append(torch.softmax(model(x), 1).numpy())
        p = np.concatenate(probs)
        active = {c: rolling_alerts(p[:, CLASSES.index(c)] >= thresholds[c], *ALERT_RULE[c])
                  for c in ANOMALIES}
        if lab == NORMAL:
            normal_h += len(s) / SAMPLE_FPS / 3600
            false_alerts += sum(int(onsets(a).sum()) for a in active.values())
        else:
            c = CLASSES[lab]
            stats[c]["n"] += 1
            if active[c].any():
                stats[c]["hit"] += 1
                stats[c]["lat"].append((int(np.argmax(active[c])) * INFER_EVERY + CLIP_LEN) / SAMPLE_FPS)
    print(f"\n{title} - event level (real alert rule)")
    for c in ANOMALIES:
        st = stats[c]
        if st["n"] == 0:
            print(f"  {c}: no segments")
            continue
        lat = f", alerted after ~{np.mean(st['lat']):.1f}s on average" if st["lat"] else ""
        print(f"  {c}: detected {st['hit']}/{st['n']} segments{lat}")
    if normal_h > 0:
        print(f"  false alerts on normal footage: {false_alerts} in {normal_h:.2f} h "
              f"({false_alerts / normal_h:.1f} per hour)")
    else:
        print("  false alerts: no normal footage in this split")


def main():
    train_ds = WindowDataset("features/train.pt", hop=TRAIN_HOP, anomaly_hop=TRAIN_ANOMALY_HOP, train=True)
    val_ds = WindowDataset("features/val.pt", hop=EVAL_HOP)

    counts = torch.bincount(train_ds.y, minlength=len(CLASSES))
    vcounts = torch.bincount(val_ds.y, minlength=len(CLASSES))
    print("train windows:", {c: int(counts[i]) for i, c in enumerate(CLASSES)})
    print("val windows:  ", {c: int(vcounts[i]) for i, c in enumerate(CLASSES)})
    for i, c in enumerate(CLASSES):
        if counts[i] == 0:
            print(f"!! no train data for '{c}' -> model can never predict it")
        elif counts[i] < MIN_WINDOWS:
            print(f"!! only {int(counts[i])} train windows for '{c}' -> expect overfitting, add more videos")
    present = [i for i in range(len(CLASSES)) if vcounts[i] > 0]
    missing_val = [CLASSES[i] for i in range(len(CLASSES)) if vcounts[i] == 0]
    if missing_val:
        print(f"!! no val data for {missing_val}: their metrics/thresholds can't be measured")

    # balanced batches: every class shows up equally often
    w = 1.0 / counts.clamp(min=1).float()
    sampler = WeightedRandomSampler(w[train_ds.y], num_samples=len(train_ds), replacement=True)
    loader = DataLoader(train_ds, batch_size=BATCH, sampler=sampler)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)

    model = TemporalTransformer()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)

    best, best_state, bad = -1.0, None, 0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total = 0.0
        for x, y in loader:
            loss = criterion(model(x), y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(y)
        sched.step()

        probs, y = predict(model, val_ds)
        pred = probs.argmax(1)
        rep = {c: prf(pred == c, y == c) for c in present}
        macro = float(np.mean([v[2] for v in rep.values()]))
        detail = " ".join(f"{CLASSES[c][:4]} P{v[0]:.2f}/R{v[1]:.2f}" for c, v in rep.items())
        print(f"ep {epoch:02d} | loss {total/len(train_ds):.4f} | val acc {(pred == y).mean():.3f} "
              f"| macroF1 {macro:.3f} | {detail}")

        if macro > best:
            best, bad = macro, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                print("early stop")
                break

    model.load_state_dict(best_state)

    # ---- one alert threshold per anomaly class (one-vs-rest precision on val) ----
    probs, y = predict(model, val_ds)
    thresholds = {}
    print(f"\nBest val macro-F1 {best:.3f}")
    for name in ANOMALIES:
        c = CLASSES.index(name)
        if vcounts[c] < MIN_VAL_WINDOWS:
            thresholds[name] = DEFAULT_THR
            print(f"  {name}: only {int(vcounts[c])} val windows -> default threshold {DEFAULT_THR} (unverified)")
            continue
        cands = [t for t in np.arange(0.50, 0.995, 0.01)
                 if (probs[:, c] >= t).any() and prf(probs[:, c] >= t, y == c)[0] >= TARGET_PRECISION]
        thr = float(min(cands)) if cands else DEFAULT_THR
        p, r, _ = prf(probs[:, c] >= thr, y == c)
        thresholds[name] = thr
        print(f"  {name}: threshold {thr:.2f} -> precision {p:.3f}, recall {r:.3f}"
              + ("" if cands else f"  (could not reach {TARGET_PRECISION:.0%} precision)"))

    torch.save({"state": best_state, "thresholds": thresholds, "classes": CLASSES}, "temporal.pth")
    print("saved temporal.pth")

    event_eval(model, "features/val.pt", thresholds, "VAL")
    if os.path.exists("features/test.pt"):
        event_eval(model, "features/test.pt", thresholds, "TEST")
        print("\nQuote the TEST numbers. Val was used to pick the model and thresholds.")


if __name__ == "__main__":
    main()