# PRD — D2C Short-Form Content Engine
**Working name:** NitroClip (placeholder)
**Owner:** Niranjan / Nitrovia Labs
**Status:** Draft v0.1 — 11 Jul 2026
**First customer:** ndevu.com (Shopify POD, faith-branded merchandise) — built as a productizable engine, not a bespoke build

---

## 1. Problem

D2C brands live or die on short-form video (TikTok, Reels, YT Shorts), which demands 3–5 posts/week. Producing one on-trend, on-brand clip today requires a creator or agency ($100–500/clip), a multi-day turnaround, and constant trend awareness. Small D2C brands (like ndevu) can't sustain this — they post sporadically, off-trend, or not at all.

Generic AI video tools (prompt → video) fail these brands for two reasons: the output isn't grounded in the brand's actual products and voice, and iteration is all-or-nothing — one bad scene means regenerating (and re-paying for) the whole clip.

## 2. Product thesis

Ingest a brand once, then turn any trending video format into an on-brand short-form clip through a script-approval → segment-generation pipeline. The human approves at the cheapest point (the script); the expensive step (video generation) happens per-segment so any scene can be regenerated without re-rendering the clip.

Three structural bets:

1. **Brand knowledge is a compounding, one-time asset.** Product shots, descriptions, and brand voice are ingested from the D2C website once and reused across every clip. Marginal cost of clip N+1 falls.
2. **The segment is the unit of work.** Script, visual direction, generated assets, render, and cost all attach to a timestamped segment. This enables partial regeneration, per-scene cost control, and a clean approval model.
3. **Trends are supplied, not scraped (v1).** The user pastes 2–3 reference videos; the system extracts the format (hook, beats, pacing) and adapts it to the brand. No fragile scraping, no platform ToS exposure.

## 3. Users

| User | Role | v1 reality (ndevu) |
|---|---|---|
| Brand operator | Supplies reference videos, approves scripts, regenerates segments, downloads clips | The son (operator, source of truth) |
| Brand owner | Reviews output, brand-safety veto | The father (decision-maker, non-technical) |
| Nitrovia | Runs ingestion, monitors pipeline, owns infra | Niru |

The two-stakeholder split at ndevu is a feature, not a bug: the script-approval gate is exactly where a non-technical decision-maker can participate. Approval must be readable by someone who will never open a JSON file.

## 4. Scope

### In scope (v1)

- **F1 — Brand Ingest** (one-time per brand, operator-run)
- **F2 — Reference Video → Format Template**
- **F3 — Storyboard: timestamped script generation + approval UI**
- **F4 — Image generation** (product assets + B-roll, per segment)
- **F5 — Segment video generation + stitching**
- **F6 — Segment regeneration**
- **F7 — Export** (MP4 + caption + hashtags)

### Explicitly out of scope (v1)

- Automated trend detection/scraping — reference videos are user-supplied
- Auto-posting / distribution / analytics — v1 ends at export; user posts manually (avoids TikTok/IG API approval processes entirely; revisit via Ayrshare/Buffer in v2)
- Timeline editor (trim/reorder UI) — regeneration replaces editing in v1
- Multi-tenancy — single-tenant deployment per brand (SMILK pattern); schema designed so tenancy is a column, not a rewrite
- Custom music/licensed audio — TTS voiceover + royalty-free bed only

## 5. Pipeline & feature detail

```
[F1 Brand Ingest]──────────────┐
                               ▼
[F2 Reference videos]──▶ [F3 Storyboard/Script] ──user approves──▶ [F4 Image Gen] ──▶ [F5 Video Gen + Stitch] ──▶ [F7 Export]
                               ▲                                                            │
                               └────────────── [F6 Regenerate segment] ◀────────────────────┘
```

### F1 — Brand Ingest
Crawl the D2C storefront (Shopify API where available — ndevu is Shopify, so use the Products API, not scraping):

- **Product shots** → original files in Supabase Storage, rows in `assets`
- **Product descriptions** → chunked + embedded into **pgvector** (not OpenSearch/FAISS — one brand's catalog is thousands of rows, not millions; a separate search cluster is infrastructure tax with no retrieval benefit at this scale; pgvector keeps embeddings joinable with product rows)
- **Brand language** → LLM-drafted `brand_voice.md` (tone, vocabulary, taboos, audience) — **human-reviewed before first use**. For ndevu: faith-context sensitivities make this file the most important brand-safety artifact in the system.

### F2 — Reference Video → Format Template
User pastes 2–3 URLs of trending Reels/TikToks/Shorts. System downloads (yt-dlp), transcribes (Whisper), and samples frames; an LLM pass extracts a **format template**: hook type, beat structure with timings, pacing, caption style, CTA placement. Stored as JSON in `format_templates` — templates are reusable across clips and, later, across brands (a productization asset in itself).

*Legal note: reference videos are analyzed for structure, never republished or trained on. Downloads are transient.*

### F3 — Storyboard (the approval gate)
LLM combines format template + brand voice + retrieved product context into a **timestamped script**: an ordered list of segments, each with `t_start/t_end`, voiceover text, on-screen caption, visual direction, and referenced product asset. Rendered in a storyboard UI (React) as cards — VO text, visual description, thumbnail placeholder. Operator edits inline and approves per-segment or whole-script.

**Nothing costing real money runs before approval.** A rejected script costs cents of LLM tokens; a rejected render costs dollars of Veo. Approved scripts are immutable and versioned — edits after approval create a new version (audit trail for the owner/operator split).

### F4 — Image generation
Per segment, generate the visual base: product-in-context shots and B-roll (Flux / Ideogram).

**POD fidelity constraint (hard requirement):** image models cannot reliably reproduce printed designs or text. For any segment showing the product, the model generates the *scene* (person, garment, environment) and the actual design file is **composited or inpainted** onto the garment from the ingested asset — never prompt-rendered. This generalizes to any brand with logos/labels and is a differentiator vs. naive gen-AI tooling.

Optional lightweight asset-approval gate here (thumbs up/down per image) before video spend.

### F5 — Video generation + stitch
Each segment's approved image(s) → image-to-video (Veo 3.1, Fast tier default) → per-segment clip. Assembly: ffmpeg concat + burned captions + TTS voiceover + royalty-free audio bed. Output: 1080×1920, 9:16, 15–40s.

Per-segment generation is what makes F6 possible and caps blast radius: a bad generation loses one 4–8s segment, not the clip.

### F6 — Segment regeneration
From the finished clip view, the operator selects any segment and regenerates at three levels: new video from same image (cheapest), new image + video, or edited direction → new script text + image + video. Restitch is local ffmpeg — effectively free. Every render is versioned; operator picks the take.

### F7 — Export
Download MP4 + LLM-generated caption + hashtags (from brand voice + format template). Post-ready package; user posts manually.

## 6. Architecture

Stack (aligned with existing Nitrovia infra): **React** (storyboard UI) · **FastAPI** (orchestrator) · **Supabase** (Postgres + pgvector + Storage) · **Railway** (hosting) · Claude API (script/voice/captions) · Flux/Ideogram (image) · Veo 3.1 (video) · Whisper + yt-dlp (reference ingestion) · ffmpeg (assembly).

Pipeline stages run as an async job queue (Postgres-backed `jobs` table is sufficient at v1 volume — no Redis/Celery yet). Every stage is idempotent and resumable; generation jobs poll provider APIs and write renders to Storage.

### Data model (core entities)

```
brands ──< products ──< assets (product shots, design files, generated)
brands ──< brand_voice (versioned .md)
format_templates (extracted from reference_videos)
projects (one clip) ── format_template, status
projects ──< segments (t_start, t_end, vo_text, caption, visual_direction,
                       product_ref, status, cost_accum)
segments ──< renders (type: image|video, provider, version, storage_path, cost)
projects ──< exports (mp4, caption, hashtags)
```

`segments` is the load-bearing table: approval state, generated assets, and cost accounting all hang off it. Multi-tenancy later = `brand_id` scoping, already present.

## 7. Unit economics

Per 30s clip (~5 segments × 6s), first pass:

| Item | Est. cost |
|---|---|
| Script + captions (Claude) | < $0.10 |
| Images, ~2/segment (Flux/Ideogram) | ~$0.50 |
| Video, Veo 3.1 Fast @ ~$0.15/s × 30s | ~$4.50 |
| TTS + stitch | ~$0.20 |
| **First-pass total** | **~$5.30** |

Standard tier (~$0.40/s) → ~$13/clip. Budget 1.5–2× for regenerations → **realistic cost ~$8–12/clip (Fast)**. At an agency-comparable price of $50–150/clip or a monthly package (e.g., 12 clips/month), gross margin is healthy. Client-supplied API keys (established Nitrovia pattern) make Nitrovia's marginal serving cost near zero for the productized-service model. *Pricing tiers shift frequently — re-verify before client quoting.*

## 8. Milestones

| # | Milestone | Demonstrates | Est. |
|---|---|---|---|
| M1 | Brand ingest + script generation (CLI/notebook OK) | ndevu products + voice → credible timestamped script from a pasted reference video | 2 wks |
| M2 | Storyboard UI + approval flow | Operator (and father) can read, edit, approve | 2 wks |
| M3 | Image gen with design compositing + video gen + stitch | First complete watchable clip | 3 wks |
| M4 | Segment regeneration + export package | Full v1 loop; ndevu posting weekly | 2 wks |

M1 is the client-demo checkpoint: a good script from *their* products and *their* chosen reference video sells the vision before any video spend.

## 9. Success metrics

- **Time to first approved clip** for a new brand: < 1 day after ingest
- **Cost per approved clip** (incl. regens): ≤ $12
- **Regeneration rate**: < 2 regens/clip average (proxy for script→visual fidelity)
- **ndevu posting cadence**: ≥ 3 clips/week sustained
- **Productization test**: brand #2 onboarded with zero code changes

## 10. Risks & open questions

- **Design compositing quality** — garment warping/lighting on composited designs is the hardest technical piece. De-risk in M3 week 1 with a spike; fallback is flat-lay product shots animated with motion effects (less impressive, always works).
- **Veo output consistency across segments** — character/style drift between segments is a known failure mode. Mitigate with shared style prompts + seed reuse; test early.
- **Reference video availability** — yt-dlp breakage against IG/TikTok is routine; keep a manual-upload fallback (user screen-records the reference).
- **Faith-content brand safety (ndevu)** — `brand_voice.md` taboo list + owner veto at script gate; no clip ships without operator approval by design.
- **Open:** pricing/packaging for the productized service (per-clip vs. monthly package) — decide after ndevu's first month of real usage data.
- **Open:** whether v2 trend layer is a curated library (editorial moat) or scraping (scale) — deferred deliberately.
