import { Link } from "react-router-dom";
import { api, Project } from "../api";
import { missingKeyMessage, usePolling } from "../hooks";
import { Button, Card, KeyBanner, StatusPill } from "../components/ui";

export default function Projects() {
  const { data: projects, error } = usePolling<Project[]>(() => api.get("/api/projects"), 4000);

  return (
    <div className="space-y-6">
      <KeyBanner message={missingKeyMessage(error)} />
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Ads</h1>
        <Link to="/projects/new"><Button>＋ Plan a new ad</Button></Link>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {(projects ?? []).map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`}>
            <Card className="transition hover:border-indigo-600">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-semibold">{p.title}</div>
                  <div className="text-xs text-zinc-400">{p.brand_name}</div>
                </div>
                <StatusPill status={p.status} />
              </div>
              {p.brief && <div className="mt-2 line-clamp-2 text-xs text-zinc-500">{p.brief}</div>}
              {p.error && <div className="mt-2 text-xs text-rose-400">⚠ {p.error}</div>}
            </Card>
          </Link>
        ))}
        {projects && projects.length === 0 && (
          <p className="text-sm text-zinc-500">Nothing yet — plan your first ad.</p>
        )}
      </div>
    </div>
  );
}
