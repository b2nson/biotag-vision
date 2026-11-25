"""
Waste Classifier webcam demo (standalone).

Needs only two files in the same folder:
    webcam_demo.py
    model_weights.npz      (made by model/train_and_save.py)

Requirements: Python 3.9+ and two packages:
    pip install numpy opencv-python

Run:
    python webcam_demo.py
Hold an item inside the green box. Press q to quit.
"""

import os
import sys
import time
from collections import deque

try:
    import numpy as np
    import cv2
except ImportError as e:
    sys.exit(f"Missing package ({e.name}). Install the requirements with:\n"
             f"    python -m pip install numpy opencv-python")

LABELS = ["Landfill", "Recycle", "Compost"]
HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_PATH = os.path.join(HERE, "model_weights.npz")


# --- Model (forward pass only, plain NumPy) -------------------------------
# Same math as the repo's model/ code, so no other files are needed.
# The layer layout is read from the weight shapes, so this works with
# both the small 2-conv model and the bigger 3-conv model:
#   4D weight -> Conv2D(pad=1) + ReLU + MaxPool(2)
#   2D weight -> Linear (+ ReLU, except the last layer)

def load_layers(path):
    if not os.path.exists(path):
        sys.exit(f"Can't find {path}\nPut model_weights.npz in the same folder as this script.")
    w = np.load(path)
    params = [w[f"param_{i}"].astype(np.float32) for i in range(len(w.files))]
    return list(zip(params[0::2], params[1::2]))  # [(weight, bias), ...]


def conv2d(x, weight, bias):
    """x (C, H, W), weight (C_out, C_in, 3, 3), padding 1 -> (C_out, H, W)"""
    k = weight.shape[-1]
    p = k // 2
    xp = np.pad(x, ((0, 0), (p, p), (p, p)))
    win = np.lib.stride_tricks.sliding_window_view(xp, (k, k), axis=(1, 2))  # (C, H, W, k, k)
    out = np.tensordot(weight, win, axes=([1, 2, 3], [0, 3, 4]))             # (C_out, H, W)
    return out + bias[:, None, None]


def max_pool2(x):
    C, H, W = x.shape
    return x[:, :H // 2 * 2, :W // 2 * 2].reshape(C, H // 2, 2, W // 2, 2).max(axis=(2, 4))


def forward(layers, x):
    """x (3, 64, 64) -> logits (3,)"""
    for i, (w, b) in enumerate(layers):
        if w.ndim == 4:
            x = max_pool2(np.maximum(conv2d(x, w, b), 0))
        else:
            x = x.reshape(-1) @ w + b
            if i < len(layers) - 1:
                x = np.maximum(x, 0)
    return x


LAYERS = load_layers(WEIGHTS_PATH)


def predict(image):
    """image: (64, 64, 3) RGB, 0-1 -> probabilities [Landfill, Recycle, Compost]"""
    logits = forward(LAYERS, image.transpose(2, 0, 1).astype(np.float32))
    e = np.exp(logits - logits.max())
    return e / e.sum()


# --- Webcam demo -----------------------------------------------------------

def preprocess(crop):
    color = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(color, (64, 64), interpolation=cv2.INTER_AREA)
    return resized.astype(np.float32) / 255.0


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    try:
        prev = time.perf_counter()
        history = deque(maxlen=8)

        while True:
            now = time.perf_counter()
            dt = now - prev
            prev = now

            ok, frame = cap.read()
            if not ok:
                break

            # center box
            h, w = frame.shape[:2]
            size = 300
            x1 = (w - size) // 2
            y1 = (h - size) // 2
            x2 = x1 + size
            y2 = y1 + size

            # crop before drawing box to avoid drawing on the crop
            crop = frame[y1:y2, x1:x2].copy()

            probs = predict(preprocess(crop))
            history.append(probs)
            avg_probs = np.mean(history, axis=0)

            i = np.argmax(avg_probs)
            text = f"{LABELS[i]} {avg_probs[i]*100:.0f}%"

            fps = 1 / dt if dt > 0 else 0
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            cv2.imshow("Waste Classifier", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()