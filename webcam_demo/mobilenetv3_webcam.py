"""Run the trained MobileNetV3 waste classifier on a webcam.

Keep this script in the same folder as mobilenetv3_waste.keras and
mobilenetv3_labels.json, then run:
    python mobilenetv3_webcam.py
Press q in the preview window to quit.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "mobilenetv3_waste.keras"
DEFAULT_LABELS = ROOT / "mobilenetv3_labels.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Trained .keras model path")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS, help="Class-index JSON path")
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index")
    parser.add_argument("--crop-size", type=int, default=300, help="Center crop size in camera pixels")
    args = parser.parse_args()
    if args.crop_size < 1:
        parser.error("crop-size must be positive")
    return args


def load_labels(path: Path, num_classes: int) -> list[str]:
    if path.exists():
        with path.open(encoding="utf-8") as labels_file:
            mapping = json.load(labels_file)
        labels = [mapping[str(index)] for index in range(num_classes)]
    else:
        labels = ["landfill", "recycle", "compost"]
        if len(labels) != num_classes:
            raise ValueError(f"No label file at {path}, and fallback labels do not match {num_classes} outputs")
        print(f"Labels file not found at {path}; using {labels}")
    return [label.replace("_", " ").title() for label in labels]


def prepare_input(crop: np.ndarray, image_size: tuple[int, int]) -> np.ndarray:
    # The model's MobileNetV3 preprocessing layer expects RGB pixel values in [0, 255].
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (image_size[1], image_size[0]), interpolation=cv2.INTER_AREA)
    return np.expand_dims(resized.astype(np.float32), axis=0)


def main() -> None:
    args = parse_args()
    if not args.model.is_file():
        raise FileNotFoundError(
            f"Trained model not found: {args.model}. "
            "Put mobilenetv3_waste.keras next to this script or pass --model."
        )

    # compile=False skips the saved training config (loss/optimizer), which isn't
    # needed for inference and can fail to load across Keras versions.
    model = tf.keras.models.load_model(args.model, compile=False)
    image_size = (int(model.input_shape[1]), int(model.input_shape[2]))
    labels = load_labels(args.labels, int(model.output_shape[-1]))
    print(f"Loaded {args.model} (input {image_size[1]}x{image_size[0]})")
    print("Press q in the preview window to quit.")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open webcam {args.camera}")

    history: deque[np.ndarray] = deque(maxlen=8)
    previous_time = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Could not read a frame from the webcam.")
                break

            height, width = frame.shape[:2]
            side = min(args.crop_size, height, width)
            x1 = (width - side) // 2
            y1 = (height - side) // 2
            x2, y2 = x1 + side, y1 + side
            crop = frame[y1:y2, x1:x2]

            batch = prepare_input(crop, image_size)
            probabilities = model(batch, training=False).numpy()[0]
            history.append(probabilities)
            average = np.mean(history, axis=0)
            best_index = int(np.argmax(average))
            confidence = float(average[best_index])

            now = time.perf_counter()
            fps = 1.0 / max(now - previous_time, 1e-8)
            previous_time = now
            color = (0, 220, 0) if confidence >= 0.6 else (0, 180, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"{labels[best_index]} {confidence * 100:.0f}%",
                (x1, max(30, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                color,
                2,
            )
            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )
            cv2.imshow("MobileNetV3 Waste Classifier", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
