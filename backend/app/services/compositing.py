"""F4 — POD fidelity compositing.

Image models can't reliably reproduce printed designs or text, so the scene is
generated with a plain garment and the brand's actual design file is pasted
onto it here. v1 is a flat alpha-composite onto the chest region — the M3
spike (warp/lighting-aware inpainting) can replace this function without
touching the rest of the pipeline. If compositing fails the un-composited
scene is used (PRD fallback: flat product shots always work)."""

import io

from PIL import Image


def composite_design(scene_bytes: bytes, design_bytes: bytes) -> bytes:
    scene = Image.open(io.BytesIO(scene_bytes)).convert("RGBA")
    design = Image.open(io.BytesIO(design_bytes)).convert("RGBA")

    # Target: centered horizontally, upper-middle (chest area) of a 9:16 frame.
    target_w = int(scene.width * 0.34)
    scale = target_w / design.width
    design = design.resize((target_w, int(design.height * scale)), Image.LANCZOS)

    x = (scene.width - design.width) // 2
    y = int(scene.height * 0.38) - design.height // 2

    # Slight transparency so the garment texture reads through.
    alpha = design.getchannel("A").point(lambda a: int(a * 0.92))
    design.putalpha(alpha)

    scene.alpha_composite(design, (x, y))
    out = io.BytesIO()
    scene.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()
