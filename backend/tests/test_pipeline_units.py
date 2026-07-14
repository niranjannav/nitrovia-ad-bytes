import io
from pathlib import Path

from PIL import Image

from app.config import MissingKeyError, PROVIDERS, provider_status
from app.services import stitch
from app.services.compositing import composite_design
from app.services.media_pipeline import _segment_duration


def _img_bytes(w, h, mode="RGB", fmt="JPEG"):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (200, 40, 40) if mode == "RGB" else (200, 40, 40, 255)).save(buf, format=fmt)
    return buf.getvalue()


def test_composite_keeps_scene_dimensions():
    scene = _img_bytes(1080, 1920)
    design = _img_bytes(600, 600, mode="RGBA", fmt="PNG")
    out = composite_design(scene, design)
    result = Image.open(io.BytesIO(out))
    assert result.size == (1080, 1920)
    assert result.format == "JPEG"


def test_segment_duration_clamped_to_veo_range():
    assert _segment_duration({"t_start": 0, "t_end": 2}) == 4       # too short -> min 4
    assert _segment_duration({"t_start": 0, "t_end": 6}) == 6
    assert _segment_duration({"t_start": 10, "t_end": 30}) == 8     # too long -> max 8


def test_segment_filter_normalizes_and_burns_caption(monkeypatch, tmp_path):
    monkeypatch.setattr(stitch, "_font", lambda: "/tmp/fake-font.ttf")
    caption_file = tmp_path / "c.txt"
    caption_file.write_text("HELLO")
    vf = stitch.build_segment_filter("HELLO", 6.0, caption_file)
    assert "scale=1080:1920" in vf and "fps=30" in vf and "drawtext" in vf
    assert str(caption_file) in vf


def test_segment_filter_without_caption(monkeypatch):
    monkeypatch.setattr(stitch, "_font", lambda: None)
    vf = stitch.build_segment_filter("", 6.0, None)
    assert "drawtext" not in vf and "crop=1080:1920" in vf


def test_provider_status_and_missing_key_message():
    status = provider_status()
    assert set(status) == set(PROVIDERS)
    err = MissingKeyError("fal", "FAL_KEY", "image generation")
    assert "FAL_KEY" in str(err) and "image generation" in str(err)
