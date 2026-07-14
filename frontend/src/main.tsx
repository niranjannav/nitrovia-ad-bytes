import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, Link, Outlet, RouterProvider } from "react-router-dom";
import "./index.css";
import { HealthStrip } from "./components/ui";
import Brands from "./pages/Brands";
import BrandDetail from "./pages/BrandDetail";
import Projects from "./pages/Projects";
import NewProject from "./pages/NewProject";
import ProjectPage from "./pages/Project";

function Layout() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-zinc-800 bg-zinc-900 px-6 py-3">
        <Link to="/" className="text-lg font-bold tracking-tight">
          ⚡ NitroClip
        </Link>
        <nav className="flex gap-4 text-sm text-zinc-300">
          <Link to="/" className="hover:text-white">Brands</Link>
          <Link to="/projects" className="hover:text-white">Ads</Link>
          <Link to="/projects/new" className="hover:text-white">＋ New ad</Link>
        </nav>
      </header>
      <HealthStrip />
      <main className="mx-auto max-w-6xl p-6">
        <Outlet />
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Brands /> },
      { path: "/brands/:id", element: <BrandDetail /> },
      { path: "/projects", element: <Projects /> },
      { path: "/projects/new", element: <NewProject /> },
      { path: "/projects/:id", element: <ProjectPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
