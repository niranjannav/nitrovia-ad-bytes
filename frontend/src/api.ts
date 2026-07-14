// Typed API client. 503 missing_key responses become MissingKeyError so pages
// can render a "fill this env var" banner instead of a generic failure.

export class MissingKeyError extends Error {
  envVar: string;
  constructor(message: string, envVar: string) {
    super(message);
    this.envVar = envVar;
  }
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const BASE = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (!res.ok) {
    if (res.status === 503 && body?.error === "missing_key") {
      throw new MissingKeyError(body.message, body.env_var);
    }
    throw new ApiError(body?.detail || body?.message || `Request failed (${res.status})`, res.status);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};

// ---- Shapes (loose on purpose; server is the source of truth) ----

export interface Health {
  ok: boolean;
  providers: Record<string, boolean>;
  ffmpeg: boolean;
  ready_to_plan: boolean;
  ready_to_generate: boolean;
  env_vars: Record<string, string>;
}

export interface Brand {
  id: string;
  name: string;
  store_url: string;
  platform: string;
  status: string;
  meta: { warnings?: string[]; product_count?: number };
  product_count?: number;
  created_at: string;
}

export interface Asset {
  id: string;
  kind: string;
  url: string | null;
}

export interface Product {
  id: string;
  title: string;
  description: string;
  price: string | null;
  product_url: string | null;
  assets: Asset[];
}

export interface BrandVoice {
  id?: string;
  version?: number;
  content_md?: string;
  status?: string;
}

export interface Render {
  id: string;
  type: "image" | "video" | "audio";
  provider: string;
  version: number;
  url: string | null;
  cost: number;
  created_at: string;
}

export interface Segment {
  id: string;
  idx: number;
  t_start: number;
  t_end: number;
  vo_text: string;
  caption: string;
  visual_direction: string;
  status: string;
  cost_accum: number;
  error: string | null;
  product: { id: string; title: string } | null;
  product_id: string | null;
  selected_image_render_id: string | null;
  selected_video_render_id: string | null;
  selected_audio_render_id: string | null;
  renders: Render[];
}

export interface ExportRow {
  id: string;
  caption: string;
  hashtags: string[];
  video_url: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  brand_id: string;
  brand_name?: string;
  title: string;
  brief: string;
  status: string;
  script_version: number;
  final_video_url?: string | null;
  error: string | null;
  segments?: Segment[];
  total_cost?: number;
  export?: ExportRow | null;
  created_at: string;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface FormatTemplate {
  id: string;
  name: string;
  template: any;
  created_at: string;
}
