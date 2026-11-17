# BioTag Vision

Computer vision for the BioTag smart bin (ECPE-196 Senior Project, University of the Pacific).

**Status: early work in progress.**

## Goal

A camera on an NVIDIA Jetson Orin Nano finds the BioTag sticker on an item and decides which bin it goes in (recycle, compost or landfill), even when the tag is covered, stained or damaged. The result shows on a screen, and an ESP32 opens the matching lid.

## Plan

1. Read the tag's code when it's visible.
2. If it can't be read, a YOLO model finds the tag and a small classifier reads it.
3. If the model isn't confident, send the item to landfill ("when in doubt, throw it out").

## What's here

| Folder | What it is |
|---|---|
| `scripts/` | Make training data, train the models, export to the Jetson |
| `app/` | Live camera + screen app |
| `esp32/` | Starter code for the bin's lid controller |
| `assets/stickers/` | Photos of the BioTag stickers, one folder per bin |

## Quick start

```bash
pip install -r requirements.txt
python scripts/make_demo_stickers.py
python scripts/make_synthetic.py --n 4000
python scripts/train_detector.py
python scripts/train_classifier.py
```

## Next steps

- [x] Photos of the real BioTag stickers
- [ ] Add the sticker photos to `assets/stickers/`
- [ ] Real photos of covered, stained and damaged tags
- [ ] First training run
- [ ] Set up and test on the Jetson
