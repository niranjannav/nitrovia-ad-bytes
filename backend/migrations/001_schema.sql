-- NitroClip v1 core schema (PRD §6). brand_id everywhere: multi-tenancy later
-- is a scoping column, not a rewrite.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE brands (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    store_url   text NOT NULL,
    platform    text NOT NULL DEFAULT 'shopify',          -- shopify | generic
    status      text NOT NULL DEFAULT 'pending',          -- pending | ingesting | ready | failed
    meta        jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id     uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    external_id  text,
    title        text NOT NULL,
    description  text NOT NULL DEFAULT '',
    product_url  text,
    price        text,
    tags         text[] NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brand_id, external_id)
);

CREATE TABLE assets (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id      uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id    uuid REFERENCES products(id) ON DELETE CASCADE,
    kind          text NOT NULL,                          -- product_shot | design_file | generated_image | generated_video | reference_frame | audio
    storage_path  text NOT NULL,
    source_url    text,
    meta          jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_assets_product ON assets(product_id);

CREATE TABLE brand_voice (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id    uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    version     int NOT NULL,
    content_md  text NOT NULL,
    status      text NOT NULL DEFAULT 'draft',            -- draft | approved
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (brand_id, version)
);

CREATE TABLE product_chunks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id    uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    product_id  uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    chunk_text  text NOT NULL,
    embedding   vector(1536)
);
CREATE INDEX idx_chunks_brand ON product_chunks(brand_id);

CREATE TABLE reference_videos (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id      uuid REFERENCES brands(id) ON DELETE SET NULL,
    url           text,
    source        text NOT NULL DEFAULT 'url',            -- url | upload
    storage_path  text,                                   -- transient download; cleared after analysis
    transcript    text,
    status        text NOT NULL DEFAULT 'pending',        -- pending | processing | analyzed | failed
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE format_templates (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name           text NOT NULL,
    reference_ids  uuid[] NOT NULL DEFAULT '{}',
    template       jsonb NOT NULL,                        -- hook type, beats, pacing, caption style, CTA placement
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id            uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    title               text NOT NULL,
    brief               text NOT NULL DEFAULT '',
    format_template_id  uuid REFERENCES format_templates(id),
    status              text NOT NULL DEFAULT 'draft',    -- draft | extracting | scripting | script_ready | approved | generating | stitching | ready | failed
    script_version      int NOT NULL DEFAULT 0,
    final_video_path    text,
    error               text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE segments (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id                uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    brand_id                  uuid NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    version                   int NOT NULL DEFAULT 1,
    idx                       int NOT NULL,
    t_start                   numeric NOT NULL,
    t_end                     numeric NOT NULL,
    vo_text                   text NOT NULL DEFAULT '',
    caption                   text NOT NULL DEFAULT '',
    visual_direction          text NOT NULL DEFAULT '',
    product_id                uuid REFERENCES products(id),
    status                    text NOT NULL DEFAULT 'draft',  -- draft | approved | generating | image_ready | video_ready | ready | failed
    cost_accum                numeric NOT NULL DEFAULT 0,
    selected_image_render_id  uuid,
    selected_video_render_id  uuid,
    selected_audio_render_id  uuid,
    error                     text,
    created_at                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_segments_project ON segments(project_id);

CREATE TABLE renders (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id    uuid NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    type          text NOT NULL,                          -- image | video | audio
    provider      text NOT NULL,
    version       int NOT NULL DEFAULT 1,
    storage_path  text NOT NULL,
    prompt        text,
    cost          numeric NOT NULL DEFAULT 0,
    meta          jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_renders_segment ON renders(segment_id);

CREATE TABLE exports (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    storage_path  text NOT NULL,
    caption       text NOT NULL DEFAULT '',
    hashtags      jsonb NOT NULL DEFAULT '[]',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type        text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'queued',           -- queued | running | done | failed
    attempts    int NOT NULL DEFAULT 0,
    error       text,
    brand_id    uuid,
    project_id  uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_status ON jobs(status) WHERE status IN ('queued', 'running');
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE INDEX idx_jobs_brand ON jobs(brand_id);
