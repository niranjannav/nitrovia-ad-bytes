import { ReactNode } from "react";
import { Health } from "../api";
import { usePolling } from "../hooks";
import { api } from "../api";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-zinc-800 bg-zinc-900/70 p-4 ${className}`}>{children}</div>;
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  className = "",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger" | "success";
  disabled?: boolean;
  className?: string;
  title?: string;
}) {
  const styles = {
    primary: "bg-indigo-600 hover:bg-indigo-500 text-white",
    success: "bg-emerald-600 hover:bg-emerald-500 text-white",
    danger: "bg-rose-700 hover:bg-rose-600 text-white",
    ghost: "bg-zinc-800 hover:bg-zinc-700 text-zinc-200",
  }[variant];
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-zinc-700 text-zinc-200",
  draft: "bg-zinc-700 text-zinc-200",
  ingesting: "bg-amber-600/30 text-amber-300",
  extracting: "bg-amber-600/30 text-amber-300",
  scripting: "bg-amber-600/30 text-amber-300",
  processing: "bg-amber-600/30 text-amber-300",
  generating: "bg-amber-600/30 text-amber-300",
  stitching: "bg-amber-600/30 text-amber-300",
  running: "bg-amber-600/30 text-amber-300",
  queued: "bg-zinc-700 text-zinc-300",
  script_ready: "bg-sky-600/30 text-sky-300",
  approved: "bg-sky-600/30 text-sky-300",
  image_ready: "bg-sky-600/30 text-sky-300",
  video_ready: "bg-sky-600/30 text-sky-300",
  analyzed: "bg-emerald-600/30 text-emerald-300",
  ready: "bg-emerald-600/30 text-emerald-300",
  done: "bg-emerald-600/30 text-emerald-300",
  failed: "bg-rose-600/30 text-rose-300",
};

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status] ?? "bg-zinc-700 text-zinc-200"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function ErrorNote({ message }: { message?: string | null }) {
  if (!message) return null;
  return <div className="mt-2 rounded-lg border border-rose-800 bg-rose-950/60 p-2 text-xs text-rose-300">{message}</div>;
}

export function KeyBanner({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <div className="mb-4 rounded-lg border border-amber-700 bg-amber-950/60 p-3 text-sm text-amber-200">
      🔑 {message}
    </div>
  );
}

const KEY_LABELS: Record<string, string> = {
  anthropic: "Claude (scripts & voice)",
  fal: "fal.ai (images & video)",
  tts: "Voiceover (Kokoro)",
  embeddings: "Embeddings (OpenRouter free)",
  stt: "Transcription (Whisper)",
  supabase: "Supabase URL",
  supabase_key: "Supabase key",
  database: "Database",
};

export function HealthStrip() {
  const { data } = usePolling<Health>(() => api.get("/health"), 10000);
  if (!data) return null;
  const missing = Object.entries(data.providers).filter(([, ok]) => !ok);
  return (
    <div className="border-b border-zinc-800 bg-zinc-900/80 px-4 py-2 text-xs">
      {missing.length === 0 && data.ffmpeg ? (
        <span className="text-emerald-400">✓ All providers configured — full pipeline available</span>
      ) : (
        <div className="flex flex-wrap items-center gap-2 text-amber-300">
          <span className="font-semibold">Setup:</span>
          {missing.map(([name]) => (
            <span key={name} className="rounded bg-amber-900/50 px-2 py-0.5" title={`Set ${data.env_vars[name]} in .env`}>
              {KEY_LABELS[name] ?? name}: set <code className="font-mono">{data.env_vars[name]}</code>
            </span>
          ))}
          {!data.ffmpeg && <span className="rounded bg-amber-900/50 px-2 py-0.5">install ffmpeg on this machine</span>}
          {missing.length === 0 && <span className="text-emerald-400">API keys ✓</span>}
        </div>
      )}
    </div>
  );
}
