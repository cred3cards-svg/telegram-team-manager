import React, { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, NavLink, useNavigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import Groups from "./pages/Groups";
import Accounts from "./pages/Accounts";
import { api } from "./api";

const NAV_ITEMS = [
  { path: "/", label: "Dashboard", icon: "⊞" },
  { path: "/inbox", label: "Inbox", icon: "✉" },
  { path: "/groups", label: "Groups", icon: "👥" },
  { path: "/accounts", label: "Accounts", icon: "📱" },
];

function Layout({ project, onProjectChange, children }) {
  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
      {/* Left nav */}
      <nav className="w-16 flex-shrink-0 bg-slate-900 border-r border-slate-700 flex flex-col items-center py-4 gap-1">
        <div className="mb-4 text-indigo-400 text-xl">✈</div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            className={({ isActive }) =>
              `w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-colors ${
                isActive
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              }`
            }
            title={item.label}
          >
            {item.icon}
          </NavLink>
        ))}
        {project && (
          <div className="mt-auto mb-2 text-[10px] text-slate-500 text-center px-1 leading-tight">
            {project.name.slice(0, 8)}
          </div>
        )}
      </nav>

      {/* Page content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        <div className="h-full overflow-auto">
          {React.cloneElement(children, { project, onProjectChange })}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [project, setProject] = useState(null);

  useEffect(() => {
    api.listProjects().then((projects) => {
      if (projects.length > 0) setProject(projects[0]);
    }).catch(console.error);
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <Layout project={project} onProjectChange={setProject}>
              <Dashboard />
            </Layout>
          }
        />
        <Route
          path="/inbox"
          element={
            <Layout project={project} onProjectChange={setProject}>
              <Inbox />
            </Layout>
          }
        />
        <Route
          path="/groups"
          element={
            <Layout project={project} onProjectChange={setProject}>
              <Groups />
            </Layout>
          }
        />
        <Route
          path="/accounts"
          element={
            <Layout project={project} onProjectChange={setProject}>
              <Accounts />
            </Layout>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
