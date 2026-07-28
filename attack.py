#!/usr/bin/env python3
"""
attack.py — score how well a TPVM-protected capture can be recovered.

    pip install opencv-python scikit-image numpy
    python attack.py capture_1_60.mp4 reference.png

Click the four white registration squares (TL, TR, BR, BL) on the first frame,
then press ENTER. Every frame is rectified to the reference geometry and each
attack is scored by SSIM against the reference.

Read the number, not the picture:
    < 0.60   protection held
    0.60-0.85 degraded but arguably usable
    > 0.85   the attack won
"""

import sys
import numpy as np
import cv2
from skimage.metrics import structural_similarity as ssim

MAX_FRAMES = 400
WON = 0.85
HELD = 0.60


# ---------------------------------------------------------------- geometry

def pick_corners(frame):
    pts, disp = [], frame.copy()
    h = 900 / max(frame.shape[:2])
    view = cv2.resize(disp, None, fx=h, fy=h)

    def on_click(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x / h, y / h))
            cv2.circle(view, (x, y), 6, (0, 255, 255), 2)
            cv2.putText(view, "TL TR BR BL".split()[len(pts) - 1],
                        (x + 10, y), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 255, 255), 2)
            cv2.imshow(win, view)

    win = "click TL, TR, BR, BL on the screen area  -  ENTER when done"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_click)
    cv2.imshow(win, view)
    while len(pts) < 4 or cv2.waitKey(20) not in (13, 10):
        if cv2.waitKey(20) == 27:
            sys.exit("cancelled")
    cv2.destroyAllWindows()
    return np.float32(pts)


def rectifier(corners, w, h):
    dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(corners, dst)
    return lambda f: cv2.warpPerspective(f, M, (w, h))


def load(path, ref_shape):
    cap = cv2.VideoCapture(path)
    ok, first = cap.read()
    if not ok:
        sys.exit(f"cannot read {path}")

    h, w = ref_shape[:2]
    warp = rectifier(pick_corners(first), w, h)

    frames = [warp(first)]
    while len(frames) < MAX_FRAMES:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(warp(f))
    cap.release()
    return np.stack(frames).astype(np.float32) / 255.0


# ---------------------------------------------------------------- scoring

def score(img, ref):
    """SSIM, with per-image gain+offset removed first.

    Exposure and white balance differences are trivially correctable by an
    attacker, so scoring them as damage would flatter the protection.
    """
    a = img.reshape(-1, 3)
    b = ref.reshape(-1, 3)
    out = np.empty_like(a)
    for c in range(3):
        A = np.vstack([a[:, c], np.ones(len(a))]).T
        gain, off = np.linalg.lstsq(A, b[:, c], rcond=None)[0]
        out[:, c] = a[:, c] * gain + off
    fixed = np.clip(out.reshape(img.shape), 0, 1)
    return ssim(fixed, ref, channel_axis=2, data_range=1.0)


# ---------------------------------------------------------------- attacks

def a_single(F):
    """Best single frame. The zero-effort attack."""
    idx = np.arange(0, len(F), max(1, len(F) // 40))
    return [(f"single frame #{i}", F[i]) for i in idx]


def a_mean(F):
    """Averaging N consecutive frames. Defeats naive A/B complementarity
    outright once N covers a whole modulation period."""
    out = []
    for n in (2, 4, 8, 16, 32):
        if len(F) < n:
            continue
        best, bi = None, 0
        for i in range(0, min(len(F) - n, 60)):
            m = F[i:i + n].mean(axis=0)
            out.append((f"mean of {n} (offset {i})", m)) if i == 0 else None
            best = m if best is None else best
        out.append((f"mean of {n} frames", F[:n].mean(axis=0)))
    return out


def a_median(F):
    """Temporal median. Rejects outlier bands better than the mean does."""
    out = []
    for n in (5, 15, 45):
        if len(F) >= n:
            out.append((f"median of {n} frames", np.median(F[:n], axis=0)))
    return out


def a_destripe(F):
    """FFT row-notch on a single frame. Rolling-shutter banding is a narrow
    band of vertical spatial frequency, so it notches cleanly."""
    f = F[len(F) // 2]
    g = cv2.cvtColor((f * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    rows = g.mean(axis=1)
    spec = np.fft.rfft(rows - rows.mean())
    mag = np.abs(spec)
    lo = 3
    if len(mag) > lo + 1:
        peak = lo + int(np.argmax(mag[lo:]))
        spec[max(lo, peak - 2):peak + 3] = 0
    profile = np.fft.irfft(spec, n=len(rows)) + rows.mean()
    gain = np.where(profile > 1e-3, rows.mean() / np.maximum(profile, 1e-3), 1.0)
    return [("FFT row-notch, 1 frame", np.clip(f * gain[:, None, None], 0, 1))]


def a_flatfield(F):
    """Estimate the illumination profile from the temporal mean, divide it out.
    This is the attack that beats fixed-phase modulation."""
    if len(F) < 8:
        return []
    prof = F.mean(axis=0).mean(axis=1, keepdims=True)
    prof = np.maximum(prof, 1e-3)
    f = F[len(F) // 2]
    return [("flat-field divide", np.clip(f / prof * prof.mean(), 0, 1))]


ATTACKS = [a_single, a_mean, a_median, a_destripe, a_flatfield]


# ---------------------------------------------------------------- main

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    vid, refpath = sys.argv[1], sys.argv[2]

    ref = cv2.imread(refpath)
    if ref is None:
        sys.exit(f"cannot read {refpath}")
    ref = ref.astype(np.float32) / 255.0

    F = load(vid, ref.shape)
    print(f"\n{len(F)} frames rectified to {ref.shape[1]}x{ref.shape[0]}\n")

    results = []
    for fn in ATTACKS:
        for name, img in fn(F):
            results.append((score(img, ref), name, img))

    results.sort(reverse=True, key=lambda r: r[0])
    seen, shown = set(), []
    for s, name, img in results:
        key = name.split("(")[0].split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        shown.append((s, name, img))

    print(f"{'SSIM':>7}   {'verdict':<12} attack")
    print("-" * 58)
    for s, name, _ in shown:
        v = "ATTACK WON" if s > WON else ("degraded" if s > HELD else "held")
        print(f"{s:7.4f}   {v:<12} {name}")

    best_s, best_n, best_i = shown[0]
    print("-" * 58)
    print(f"\nbest recovery: {best_n}  ->  SSIM {best_s:.4f}")
    if best_s > WON:
        print("The modulation did not survive. Raise amplitude, or randomise the")
        print("waveform so no single exposure or averaging window nulls it.")
    elif best_s > HELD:
        print("Partial. Usable frames are recoverable with effort — check whether")
        print("the text in the chart is still legible before calling this a pass.")
    else:
        print("Held against these attacks. Note this says nothing about a")
        print("global-shutter sensor, which this approach cannot touch.")

    cv2.imwrite("best_recovery.png", (best_i * 255).astype(np.uint8))
    print("\nwrote best_recovery.png — look at it. The number is not the whole story.")


if __name__ == "__main__":
    main()
