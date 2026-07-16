# NitroClip — D2C Short-Form Ad Engine

Ingest a brand's storefront once, then turn any trending video format into an
on-brand short-form ad (9:16, 15–40s) through a script-approval →
segment-generation pipeline. See `PRD_D2C_ShortForm_Engine.md` for the full
product spec.

**The flow:** paste a store URL → products + brand voice are ingested → paste
2–3 trending reference video URLs → a timestamped script is generated → you
review/edit/approve it in the storyboard UI (**nothing costing real money runs
before approval**) → images, per-segment video and voiceover are generated →
stitched into an MP4 → regenerate any segment at three cost levels → export
MP4 + caption + hashtags.

## Prerequisites

- Python 3.11+, Node 20+, **ffmpeg** (`brew install ffmpeg` / `apt install ffmpeg`)
- A free [Supabase](https://supabase.com) project (Postgres + pgvector + storage)
- API keys — see `.env.example` for exactly where to get each one

## Setup

```bash
cp .env.example .env        # fill in keys as you obtain them
make setup                  # installs backend venv + frontend node_modules
make dev                    # starts API (:8000) + worker + UI (:5173)
```

Open http://localhost:5173. The banner at the top shows which keys are still
missing and what each unlocks — the app is usable incrementally:

| Keys filled | What works |
|---|---|
| none | UI loads, /health reports missing keys |
| Supabase + `DATABASE_URL` | Brand ingest (products + images, no voice/embeddings) |
| + `ANTHROPIC_API_KEY` | Brand voice, format templates, **script generation + storyboard approval** |
| + `OPENROUTER_API_KEY` | Semantic product retrieval (NVIDIA's **free** embedding model) |
| + `FAL_KEY` | **Full pipeline**: image gen, video gen, Kokoro voiceover, stitched clips, export |
| + `OPENAI_API_KEY` (optional) | Whisper transcripts of reference videos (frames-only analysis works without) |

The database schema is applied automatically on first boot (plain SQL
migrations in `backend/migrations/`, tracked in `schema_migrations`). To apply
manually: `make migrate`.

## Using it

1. **Brands** → paste your store URL. Shopify stores are read via the public
   `/products.json` (no key needed); other platforms get a best-effort scrape.
2. Review the drafted **brand voice** (tone / vocabulary / taboos) and approve
   it — every script is written against this document.
3. **New ad** → pick the brand, paste 2–3 reference video URLs (or upload a
   screen recording if the platform blocks downloads, or reuse a saved
   template).
4. **Storyboard** → edit segments inline, approve per-segment or all at once,
   then *Generate media*.
5. **Clip view** → watch the stitched result, regenerate any segment
   (video-only / image+video / everything), pick between takes, restitch.
6. **Export** → download the MP4 and copy the generated caption + hashtags.
   Post manually — v1 deliberately ends at export.

## Architecture

```
frontend/   React + Vite + Tailwind  (storyboard/approval UI)
backend/
  app/main.py        FastAPI + in-process job worker
  app/worker.py      Postgres-backed job queue (SELECT ... FOR UPDATE SKIP LOCKED)
  app/services/      ingest → reference → storyboard → media_pipeline → stitch → exporter
  app/providers/     llm (Claude) · audio (OpenAI) · media (fal.ai)
  migrations/        plain SQL, applied in order
```

Providers are isolated behind `app/providers/` — swapping e.g. fal for
Replicate touches one file. Cost estimates per render accumulate on
`segments.cost_accum` (tune `EST_*` env vars).

### Cheap / local inference (audio + embeddings)

Voiceover, embeddings and transcription each speak the OpenAI-compatible API
and switch between cloud and local with env vars only:

| Capability | Cloud default | Local ($0, e.g. Apple Silicon) |
|---|---|---|
| Voiceover | Kokoro 82M on fal.ai (`FAL_KEY`, ~$0.02/1k chars) | `TTS_PROVIDER=local` → in-process kokoro-onnx (`pip install -r backend/requirements-local.txt`; ~330MB model auto-downloads) |
| Embeddings | NVIDIA `llama-nemotron-embed-vl-1b-v2:free` on OpenRouter ($0) | `EMBEDDINGS_BASE_URL=http://localhost:11434/v1` + Ollama (`ollama pull nomic-embed-text`) |
| Transcription | OpenAI Whisper (~$0.006/min) | `STT_BASE_URL` → speaches / LM Studio |

A third TTS mode (`TTS_PROVIDER=openai_compatible`) accepts any
`/v1/audio/speech` endpoint. **After switching embedding models, re-ingest the
brand** — vectors from different models aren't comparable, so retrieval falls
back to recency until chunks are re-embedded (each chunk records its
`embedding_model`).

**Design compositing (POD fidelity):** image models can't reproduce printed
designs, so scenes are generated with a plain garment and the actual design
asset is composited on (`app/services/compositing.py`). v1 is a flat
alpha-composite; the planned M3 spike (warp/lighting-aware inpainting) replaces
that one function.

**Music bed:** drop royalty-free `.mp3`s in `backend/assets/music/` to have a
bed mixed under the voiceover.

## Tests

```bash
make test    # backend unit tests — providers mocked, no paid calls
```

## Deploying later

The PRD targets Railway: deploy `backend/` (uvicorn) and `frontend/` (static
build) as two services, set the same env vars, and point `VITE_API_URL` at the
backend. Single-tenant per brand by design; `brand_id` is already on every
table so multi-tenancy is a scoping change, not a rewrite.
