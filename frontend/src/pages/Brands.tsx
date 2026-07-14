import { useState } from "react";
import { Link } from "react-router-dom";
import { api, Brand } from "../api";
import { missingKeyMessage, usePolling } from "../hooks";
import { Button, Card, ErrorNote, KeyBanner, StatusPill } from "../components/ui";

export default function Brands() {
  const { data: brands, error, refresh } = usePolling<Brand[]>(() => api.get("/api/brands"), 4000);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const create = async () => {
    if (!url.trim()) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await api.post("/api/brands", { name: name.trim() || new URL(normalize(url)).hostname, store_url: url.trim() });
      setName("");
      setUrl("");
      refresh();
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <KeyBanner message={missingKeyMessage(error)} />
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Ingest a brand</h2>
        <p className="mb-3 text-sm text-zinc-400">
          Paste a store URL (Shopify works best). Products, images and descriptions are pulled in once and reused
          across every ad; a brand-voice document is drafted for your review.
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            className="w-72 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            placeholder="https://your-store.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <input
            className="w-56 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
            placeholder="Brand name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button onClick={create} disabled={submitting || !url.trim()}>
            {submitting ? "Starting…" : "Ingest store"}
          </Button>
        </div>
        <ErrorNote message={formError} />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {(brands ?? []).map((b) => (
          <Link key={b.id} to={`/brands/${b.id}`}>
            <Card className="transition hover:border-indigo-600">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold">{b.name}</div>
                  <div className="text-xs text-zinc-400">{b.store_url}</div>
                </div>
                <StatusPill status={b.status} />
              </div>
              <div className="mt-2 text-xs text-zinc-400">
                {b.product_count ?? 0} products · {b.platform}
              </div>
              {(b.meta?.warnings?.length ?? 0) > 0 && (
                <div className="mt-2 text-xs text-amber-400">⚠ {b.meta.warnings![0]}</div>
              )}
            </Card>
          </Link>
        ))}
        {brands && brands.length === 0 && (
          <p className="text-sm text-zinc-500">No brands yet — ingest your first store above.</p>
        )}
      </div>
    </div>
  );
}

function normalize(u: string) {
  return u.startsWith("http") ? u : `https://${u}`;
}
