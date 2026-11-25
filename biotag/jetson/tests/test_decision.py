import copy

from biotag.config import DEFAULTS
from biotag.decision import DecisionEngine
from biotag.materials import Materials
from biotag.types import Detection, Observation, Tag, TagRead


def engine(overrides=None, **cfg):
    c = copy.deepcopy(DEFAULTS["decision"])
    c.update(cfg)
    return DecisionEngine(c, Materials(local_overrides=overrides))


def tag_obs(material="PET", bin_id="R"):
    return Observation(TagRead(Tag("000001", material, bin_id, "raw")))


def vision_obs(material, conf, damaged=False):
    return Observation(TagRead(damaged=damaged), [Detection(material, conf, material.lower())], True)


def run(e, obs, seconds, start=0.0, fps=30):
    """Feed the same observation for a while; return (decision, time)."""
    for i in range(int(seconds * fps)):
        now = start + i / fps
        d = e.update(obs, now)
        if d:
            return d, now
    return None, start + seconds


def test_tag_wins_immediately():
    d = engine().update(tag_obs("PET", "R"), 0.0)
    assert (d.bin, d.source, d.material, d.item_id) == ("R", "tag", "PET", "000001")


def test_compost_tag():
    assert engine().update(tag_obs("PLA", "C"), 0.0).bin == "C"


def test_local_override_beats_tag():
    assert engine(overrides={"PLA": "L"}).update(tag_obs("PLA", "C"), 0.0).bin == "L"


def test_unknown_material_uses_bin_from_tag():
    d = engine().update(tag_obs("NEWSTUFF", "C"), 0.0)
    assert d.bin == "C" and d.material == "NEWSTUFF"


def test_vision_needs_grace_period_and_votes():
    e = engine()
    d, t = run(e, vision_obs("ALU", 0.9), 2.0)
    assert d.bin == "R" and d.source == "vision"
    assert t >= e.cfg["tag_grace_s"] - 1e-6          # the tag got its chance first
    assert "No tag" in d.reason


def test_damaged_tag_reason():
    d, _ = run(engine(), vision_obs("GLASS", 0.9, damaged=True), 2.0)
    assert d.source == "vision" and "damaged" in d.reason.lower()


def test_low_confidence_goes_to_landfill_as_unsure():
    e = engine()
    d, t = run(e, vision_obs("ALU", 0.4), 5.0)
    assert (d.bin, d.source) == ("L", "unsure")
    assert t >= e.cfg["unsure_after_s"] - 1e-6


def test_present_but_nothing_detected_is_unsure():
    d, _ = run(engine(), Observation(present=True), 5.0)
    assert (d.bin, d.source) == ("L", "unsure")


def test_nothing_present_never_decides():
    d, _ = run(engine(), Observation(), 10.0)
    assert d is None


def test_flicker_does_not_trigger():
    e = engine()
    for i in range(300):                 # one confident frame in ten
        now = i / 30
        obs = vision_obs("ALU", 0.9) if i % 10 == 0 else Observation()
        d = e.update(obs, now)
        assert d is None or d.source != "vision"


def test_item_removed_resets_timer():
    e = engine()
    assert run(e, Observation(present=True), 2.0)[0] is None
    assert run(e, Observation(), 1.0, start=2.0)[0] is None       # taken away
    d, t = run(e, Observation(present=True), 5.0, start=3.0)
    assert d.source == "unsure" and t - 3.0 >= e.cfg["unsure_after_s"] - 1e-6


def test_contamination_reroutes_recyclable():
    e = engine()
    obs = Observation(TagRead(), [Detection("CARDBOARD", 0.9, "cardboard"),
                                  Detection("CONTAM", 0.8, "food_stain")], True)
    d, _ = run(e, obs, 2.0)
    assert d.bin == "L" and d.material == "CARDBOARD" and "residue" in d.reason


def test_contamination_also_overrides_tag():
    e = engine()
    e.update(Observation(TagRead(), [Detection("CONTAM", 0.9, "liquid")], True), 0.0)
    assert e.update(tag_obs("PET", "R"), 0.1).bin == "L"


def test_contamination_does_not_move_compost():
    e = engine()
    e.update(Observation(TagRead(), [Detection("CONTAM", 0.9, "food_stain")], True), 0.0)
    assert e.update(tag_obs("FIBER", "C"), 0.1).bin == "C"


def test_majority_material_wins():
    e = engine()
    d = None
    for i in range(90):
        obs = vision_obs("PAPER", 0.7) if i % 4 == 0 else vision_obs("ALU", 0.85)
        d = e.update(obs, i / 30)
        if d:
            break
    assert d.material == "ALU"
