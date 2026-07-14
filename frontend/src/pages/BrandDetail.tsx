import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Brand, BrandVoice, Product } from "../api";
import { missingKeyMessage, usePolling } from "../hooks";
import { Button, Card, ErrorNote, KeyBanner, StatusPill } from "../components/ui";

export default function BrandDetail() {
  const { id } = useParams();
  const { data: brand, error } = usePolling<Brand>(() => api.get(`/api/brands/${id}`), 4000);
  const busy = brand?.status === "ingesting" || brand?.status === "pending";
  const { data: products } = usePolling<Product[]>(() => api.get(`/api/brands/${id}/products`), 5000, busy);
  const { data: voice, refresh: refreshVoice } = usePolling<BrandVoice>(() => api.get(`/api/brands/${id}/voice`), 5000, busy);

  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty && voice?.content_md !== undefined) setDraft(voice.content_md ?? "");
  }, [voice?.content_md, dirty]);

  const saveVoice = async (approve: boolean) => {
    setSaveError(null);
    try {
      await api.put(`/api/brands/${id}/voice`, { content_md: draft, approve });
      setDirty(false);
      refreshVoice();
    } catch (e) {
      setSaveError((e as Error).message);
    }
  };

  if (!brand) return <KeyBanner message={missingKeyMessage(error)} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{brand.name}</h1>
          <a href={brand.store_url} target="_blank" rel="noreferrer" className="text-sm text-indigo-400 hover:underline">
            {brand.store_url}
          </a>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill status={brand.status} />
          <Button variant="ghost" onClick={() => api.post(`/api/brands/${id}/reingest`)}>Re-ingest</Button>
          <Link to="/projects/new"><Button variant="success">Create ad →</Button></Link>
        </div>
      </div>
      {busy && <p className="text-sm text-amber-300">Ingesting the store — products and brand voice will appear here as they land…</p>}
      {(brand.meta?.warnings?.length ?? 0) > 0 && (
        <Card className="border-amber-800">
          <div className="text-sm font-semibold text-amber-300">Ingest warnings</div>
          <ul className="mt-1 list-inside list-disc text-xs text-amber-200/80">
            {brand.meta.warnings!.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </Card>
      )}

      <Card>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            Brand voice{" "}
            {voice?.version ? <span className="text-xs text-zinc-400">v{voice.version} · {voice.status}</span> : null}
          </h2>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => saveVoice(false)} disabled={!dirty}>Save draft</Button>
            <Button variant="success" onClick={() => saveVoice(true)}>Approve voice</Button>
          </div>
        </div>
        <p className="mb-2 text-xs text-zinc-400">
          The single most important brand-safety artifact: tone, vocabulary, taboos, audience. Review and edit before
          generating your first ad — every script is written against this document.
        </p>
        <textarea
          className="h-72 w-full rounded-lg border border-zinc-700 bg-zinc-950 p-3 font-mono text-xs"
          value={draft}
          placeholder={busy ? "Drafting…" : "No brand voice yet. It is drafted automatically during ingest (needs ANTHROPIC_API_KEY), or write your own here."}
          onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
        />
        <ErrorNote message={saveError} />
      </Card>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Products ({products?.length ?? 0})</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(products ?? []).map((p) => (
            <Card key={p.id}>
              {p.assets[0]?.url && (
                <img src={p.assets[0].url} alt={p.title} className="mb-2 h-40 w-full rounded-lg object-cover" />
              )}
              <div className="text-sm font-medium">{p.title}</div>
              <div className="text-xs text-zinc-400">{p.price ? `$${p.price}` : ""}</div>
              <div className="mt-1 line-clamp-2 text-xs text-zinc-500">{p.description}</div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
