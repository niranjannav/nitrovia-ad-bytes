import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, Job, Project, Render, Segment } from "../api";
import { missingKeyMessage, usePolling } from "../hooks";
import { Button, Card, ErrorNote, KeyBanner, StatusPill } from "../components/ui";

export default function ProjectPage() {
  const { id } = useParams();
  const { data: project, error, refresh } = usePolling<Project>(() => api.get(`/api/projects/${id}`), 3000);
  const { data: jobs } = usePolling<Job[]>(() => api.get(`/api/projects/${id}/jobs`), 3000);
  const [actionError, setActionError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  if (!project) return <KeyBanner message={missingKeyMessage(error)} />;

  const segments = project.segments ?? [];
  const allApproved = segments.length > 0 && segments.every((s) => s.status !== "draft");
  const anyDraft = segments.some((s) => s.status === "draft");
  const working = ["extracting", "scripting", "generating", "stitching"].includes(project.status);
  const activeJob = jobs?.find((j) => j.status === "running" || j.status === "queued");

  return (
    <div className="space-y-6">
      <KeyBanner message={missingKeyMessage(error)} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">{project.title}</h1>
          <div className="text-sm text-zinc-400">{project.brief}</div>
        </div>
        <div className="flex items-center gap-3">
          {project.total_cost !== undefined && project.total_cost > 0 && (
            <span className="text-xs text-zinc-400">est. spend ${project.total_cost.toFixed(2)}</span>
          )}
          <StatusPill status={project.status} />
        </div>
      </div>

      {working && (
        <Card className="border-amber-800">
          <span className="text-sm text-amber-300">
            ⏳ {project.status === "extracting" && "Analyzing reference videos & extracting the format template…"}
            {project.status === "scripting" && "Writing the timestamped script…"}
            {project.status === "generating" && "Generating images, video and voiceover per segment…"}
            {project.status === "stitching" && "Stitching segments into the final clip…"}
            {activeJob && <span className="ml-2 text-xs text-amber-200/70">({activeJob.type})</span>}
          </span>
        </Card>
      )}
      <ErrorNote message={project.error} />
      <ErrorNote message={actionError} />

      {segments.length === 0 && !working && project.status !== "failed" && (
        <p className="text-sm text-zinc-400">Waiting for the script…</p>
      )}
      {project.status === "failed" && (
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => act(() => api.post(`/api/projects/${id}/regenerate_script`))}>
            Retry script generation
          </Button>
        </div>
      )}

      {segments.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Storyboard <span className="text-xs font-normal text-zinc-400">v{project.script_version} — the approval gate: nothing costing real money runs before you approve</span></h2>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => act(() => api.post(`/api/projects/${id}/regenerate_script`))}>
                ↻ Rewrite script
              </Button>
              {anyDraft && (
                <Button variant="success" onClick={() => act(() => api.post(`/api/projects/${id}/approve`))}>
                  ✓ Approve whole script
                </Button>
              )}
              {allApproved && (
                <Button onClick={() => act(() => api.post(`/api/projects/${id}/generate`))} disabled={working}>
                  🎬 Generate media
                </Button>
              )}
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {segments.map((s) => (
              <SegmentCard key={s.id} segment={s} onAction={act} projectStatus={project.status} />
            ))}
          </div>
        </>
      )}

      {project.final_video_url && (
        <Card>
          <h2 className="mb-3 text-lg font-semibold">Final clip</h2>
          <div className="flex flex-wrap gap-6">
            <video src={project.final_video_url} controls className="h-96 rounded-xl border border-zinc-800" />
            <div className="max-w-md space-y-3">
              <div className="flex gap-2">
                <a href={project.final_video_url} download>
                  <Button>⬇ Download MP4</Button>
                </a>
                <Button variant="ghost" onClick={() => act(() => api.post(`/api/projects/${id}/stitch`))}>
                  ↻ Restitch
                </Button>
                <Button variant="success" onClick={() => act(() => api.post(`/api/projects/${id}/export`))}>
                  📦 {project.export ? "Regenerate caption" : "Generate caption + hashtags"}
                </Button>
              </div>
              {project.export && (
                <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
                  <div className="whitespace-pre-wrap">{project.export.caption}</div>
                  <div className="text-indigo-300">{project.export.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}</div>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      navigator.clipboard.writeText(
                        `${project.export!.caption}\n\n${project.export!.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}`
                      )
                    }
                  >
                    Copy caption + tags
                  </Button>
                </div>
              )}
              <p className="text-xs text-zinc-500">Post it manually — v1 ends at export by design.</p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function SegmentCard({
  segment,
  onAction,
  projectStatus,
}: {
  segment: Segment;
  onAction: (fn: () => Promise<unknown>) => void;
  projectStatus: string;
}) {
  const [editing, setEditing] = useState(false);
  const [vo, setVo] = useState(segment.vo_text);
  const [caption, setCaption] = useState(segment.caption);
  const [direction, setDirection] = useState(segment.visual_direction);

  const image = segment.renders.find((r) => r.id === segment.selected_image_render_id);
  const video = segment.renders.find((r) => r.id === segment.selected_video_render_id);
  const videoTakes = segment.renders.filter((r) => r.type === "video");
  const generated = segment.renders.length > 0;

  const save = () =>
    onAction(async () => {
      await api.put(`/api/segments/${segment.id}`, { vo_text: vo, caption, visual_direction: direction });
      setEditing(false);
    });

  return (
    <Card>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">
          #{segment.idx + 1} · {Number(segment.t_start).toFixed(0)}–{Number(segment.t_end).toFixed(0)}s
          {segment.product && <span className="ml-2 text-xs font-normal text-indigo-300">🛍 {segment.product.title}</span>}
        </div>
        <StatusPill status={segment.status} />
      </div>

      <div className="flex gap-3">
        <div className="w-28 shrink-0">
          {video?.url ? (
            <video src={video.url} controls muted className="w-28 rounded-lg border border-zinc-800" />
          ) : image?.url ? (
            <img src={image.url} className="w-28 rounded-lg border border-zinc-800" />
          ) : (
            <div className="flex h-44 w-28 items-center justify-center rounded-lg border border-dashed border-zinc-700 text-2xl text-zinc-600">
              {segment.status === "generating" ? "⏳" : "🎞"}
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1 space-y-2 text-sm">
          {editing ? (
            <>
              <Field label="Voiceover" value={vo} onChange={setVo} />
              <Field label="Caption" value={caption} onChange={setCaption} />
              <Field label="Visual direction" value={direction} onChange={setDirection} rows={3} />
              <div className="flex gap-2">
                <Button onClick={save}>Save</Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </>
          ) : (
            <>
              <div><span className="text-xs uppercase text-zinc-500">VO</span> {segment.vo_text || <em className="text-zinc-500">none</em>}</div>
              <div><span className="text-xs uppercase text-zinc-500">Caption</span> {segment.caption || <em className="text-zinc-500">none</em>}</div>
              <div className="text-zinc-400"><span className="text-xs uppercase text-zinc-500">Visual</span> {segment.visual_direction}</div>
            </>
          )}
          <ErrorNote message={segment.error} />
        </div>
      </div>

      {!editing && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => setEditing(true)}>✎ Edit</Button>
          {segment.status === "draft" && (
            <Button variant="success" onClick={() => onAction(() => api.post(`/api/segments/${segment.id}/approve`))}>
              ✓ Approve
            </Button>
          )}
          {generated && segment.status !== "generating" && (
            <>
              <Button
                variant="ghost"
                title="New video from the same image — cheapest"
                onClick={() => onAction(() => api.post(`/api/segments/${segment.id}/regenerate`, { level: "video" }))}
              >
                ↻ Video
              </Button>
              <Button
                variant="ghost"
                title="New image, then new video"
                onClick={() => onAction(() => api.post(`/api/segments/${segment.id}/regenerate`, { level: "image_video" }))}
              >
                ↻ Image + video
              </Button>
              <Button
                variant="ghost"
                title="Regenerate everything from the (edited) direction, incl. voiceover"
                onClick={() =>
                  onAction(() =>
                    api.post(`/api/segments/${segment.id}/regenerate`, {
                      level: "full",
                      vo_text: vo,
                      caption,
                      visual_direction: direction,
                    })
                  )
                }
              >
                ↻ Everything
              </Button>
            </>
          )}
        </div>
      )}

      {videoTakes.length > 1 && (
        <div className="mt-3 border-t border-zinc-800 pt-2">
          <div className="mb-1 text-xs uppercase text-zinc-500">Takes — pick one, then restitch</div>
          <div className="flex flex-wrap gap-2">
            {videoTakes.map((r: Render) => (
              <button
                key={r.id}
                onClick={() => onAction(() => api.post(`/api/segments/${segment.id}/select_render`, { render_id: r.id }))}
                className={`rounded px-2 py-1 text-xs ${
                  r.id === segment.selected_video_render_id ? "bg-indigo-600 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                }`}
              >
                v{r.version}
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function Field({ label, value, onChange, rows = 2 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  return (
    <div>
      <label className="text-xs uppercase text-zinc-500">{label}</label>
      <textarea
        rows={rows}
        className="w-full rounded-lg border border-zinc-700 bg-zinc-950 p-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
