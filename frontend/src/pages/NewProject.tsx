import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Brand, FormatTemplate, Project } from "../api";
import { missingKeyMessage, usePolling } from "../hooks";
import { Button, Card, ErrorNote, KeyBanner } from "../components/ui";

export default function NewProject() {
  const navigate = useNavigate();
  const { data: brands, error } = usePolling<Brand[]>(() => api.get("/api/brands"), 15000, false);
  const { data: templates } = usePolling<FormatTemplate[]>(() => api.get("/api/templates"), 15000, false);

  const [brandId, setBrandId] = useState("");
  const [title, setTitle] = useState("");
  const [brief, setBrief] = useState("");
  const [mode, setMode] = useState<"urls" | "template">("urls");
  const [urls, setUrls] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [uploadedIds, setUploadedIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const selectedBrand = brandId || brands?.[0]?.id || "";

  const uploadFile = async (file: File) => {
    setUploading(true);
    setFormError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const ref = await api.upload<{ id: string }>("/api/references/upload", form);
      setUploadedIds((ids) => [...ids, ref.id]);
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const create = async () => {
    setSubmitting(true);
    setFormError(null);
    try {
      const project = await api.post<Project>("/api/projects", {
        brand_id: selectedBrand,
        title: title.trim() || "Untitled ad",
        brief: brief.trim(),
        format_template_id: mode === "template" ? templateId || null : null,
        reference_urls: mode === "urls" ? urls.split("\n").map((u) => u.trim()).filter(Boolean) : [],
        uploaded_reference_ids: mode === "urls" ? uploadedIds : [],
      });
      navigate(`/projects/${project.id}`);
    } catch (e) {
      setFormError((e as Error).message);
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <KeyBanner message={missingKeyMessage(error)} />
      <h1 className="text-xl font-bold">Plan a new ad</h1>

      <Card className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">Brand</label>
          <select
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            value={selectedBrand}
            onChange={(e) => setBrandId(e.target.value)}
          >
            {(brands ?? []).map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          {brands && brands.length === 0 && (
            <p className="mt-1 text-xs text-amber-300">Ingest a brand first (Brands page).</p>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Title</label>
          <input
            className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            placeholder="e.g. Faith Over Fear hoodie — winter push"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Brief (optional)</label>
          <textarea
            className="h-20 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            placeholder="What should this ad push? Products, angle, offer, season…"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
          />
        </div>

        <div>
          <label className="mb-2 block text-sm font-medium">Trend format</label>
          <div className="mb-3 flex gap-2 text-sm">
            <button
              className={`rounded-lg px-3 py-1.5 ${mode === "urls" ? "bg-indigo-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
              onClick={() => setMode("urls")}
            >
              From reference videos
            </button>
            <button
              className={`rounded-lg px-3 py-1.5 ${mode === "template" ? "bg-indigo-600 text-white" : "bg-zinc-800 text-zinc-300"}`}
              onClick={() => setMode("template")}
            >
              Reuse a saved template
            </button>
          </div>

          {mode === "urls" ? (
            <div className="space-y-2">
              <textarea
                className="h-24 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
                placeholder={"Paste 2-3 trending TikTok / Reels / Shorts URLs, one per line.\nThe system extracts the format (hook, beats, pacing) — the videos are never republished."}
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
              />
              <div className="flex items-center gap-2 text-xs text-zinc-400">
                <span>Download blocked?</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept="video/*"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])}
                />
                <Button variant="ghost" onClick={() => fileRef.current?.click()} disabled={uploading}>
                  {uploading ? "Uploading…" : "Upload a screen recording"}
                </Button>
                {uploadedIds.length > 0 && <span className="text-emerald-400">{uploadedIds.length} uploaded ✓</span>}
              </div>
            </div>
          ) : (
            <select
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
            >
              <option value="">Choose a template…</option>
              {(templates ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          )}
        </div>

        <Button onClick={create} disabled={submitting || !selectedBrand}>
          {submitting ? "Creating…" : "Generate script →"}
        </Button>
        <p className="text-xs text-zinc-500">
          This only writes the script (costs cents). Nothing that costs real money runs until you approve the
          storyboard.
        </p>
        <ErrorNote message={formError} />
      </Card>
    </div>
  );
}
