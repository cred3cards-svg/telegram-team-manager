import React, { useState, useEffect } from "react";
import { api } from "../api";
import DiscoveryPanel from "../components/DiscoveryPanel";

export default function Dashboard({ project, onProjectChange }) {
  const [projects, setProjects] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [chats, setChats] = useState([]);
  const [awayLog, setAwayLog] = useState([]);
  const [isCreating, setIsCreating] = useState(false);
  const [newProject, setNewProject] = useState({ name: "", tone: "casual", context: "", system_prompt: "" });
  const [editProject, setEditProject] = useState(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error);
  }, []);

  useEffect(() => {
    if (!project) return;
    Promise.all([
      api.listAccounts(project.id),
      api.getInbox(project.id),
      api.awayLog(project.id),
    ]).then(([accs, inbox, log]) => {
      setAccounts(accs);
      setChats(inbox);
      setAwayLog(log);
    });
  }, [project]);

  async function handleCreateProject() {
    if (!newProject.name.trim()) return;
    const created = await api.createProject(newProject.name, newProject.tone, newProject.context, newProject.system_prompt);
    setProjects((prev) => [...prev, created]);
    onProjectChange(created);
    setIsCreating(false);
    setNewProject({ name: "", tone: "casual", context: "", system_prompt: "" });
  }

  async function handleUpdateProject() {
    if (!editProject) return;
    const updated = await api.updateProject(editProject.id, {
      name: editProject.name,
      tone: editProject.tone,
      context: editProject.context,
      system_prompt: editProject.system_prompt || "",
    });
    setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    if (project?.id === updated.id) onProjectChange(updated);
    setEditProject(null);
  }

  const unread = chats.reduce((s, c) => s + (c.unread_count || 0), 0);

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold text-slate-100">Dashboard</h2>
        <button
          onClick={() => setIsCreating(true)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl px-4 py-2 text-sm font-medium transition-colors"
        >
          + New Project
        </button>
      </div>

      {/* Project selector */}
      {projects.length > 0 && (
        <div className="mb-6">
          <label className="text-xs text-slate-400 uppercase tracking-wide mb-2 block">Active Project</label>
          <div className="flex flex-wrap gap-2">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => onProjectChange(p)}
                className={`px-4 py-2 rounded-xl text-sm transition-colors ${
                  project?.id === p.id
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Stats */}
      {project && (
        <div className="grid grid-cols-4 gap-4 mb-8">
          <StatCard label="Accounts" value={accounts.length} icon="📱" />
          <StatCard label="Conversations" value={chats.length} icon="💬" />
          <StatCard label="Unread" value={unread} icon="🔴" highlight={unread > 0} />
          <StatCard
            label="Away Replies"
            value={awayLog.filter((l) => !l.reviewed).length}
            icon="🌙"
            highlight={awayLog.some((l) => !l.reviewed)}
          />
        </div>
      )}

      {/* Create Project Modal */}
      {isCreating && (
        <ProjectForm
          title="New Project"
          data={newProject}
          onChange={setNewProject}
          onSave={handleCreateProject}
          onCancel={() => setIsCreating(false)}
        />
      )}

      {/* Away Log */}
      {project && awayLog.length > 0 && (
        <AwayLogPanel
          log={awayLog}
          onMarkReviewed={async (id) => {
            await api.awayMarkReviewed(id);
            setAwayLog((prev) => prev.map((l) => l.id === id ? { ...l, reviewed: 1 } : l));
          }}
          onMarkAllReviewed={async () => {
            await api.awayMarkAllReviewed(project.id);
            setAwayLog((prev) => prev.map((l) => ({ ...l, reviewed: 1 })));
          }}
        />
      )}

      {/* Group Discovery — always show when project is active */}
      {project && (
        <DiscoveryPanel accounts={accounts} project={project} />
      )}

      {/* Edit Project */}
      {project && !isCreating && (
        <div className="bg-slate-800 rounded-2xl border border-slate-700 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-slate-200">Project Settings</h3>
            {editProject ? null : (
              <button
                onClick={() => setEditProject({ ...project })}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Edit
              </button>
            )}
          </div>

          {editProject ? (
            <ProjectForm
              title=""
              data={editProject}
              onChange={(val) => setEditProject((prev) => ({ ...prev, ...val }))}
              onSave={handleUpdateProject}
              onCancel={() => setEditProject(null)}
            />
          ) : (
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex gap-2">
                <span className="text-slate-400 w-24 flex-shrink-0">Name</span>
                <span className="text-slate-100">{project.name}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-slate-400 w-24 flex-shrink-0">Tone</span>
                <span className="capitalize text-slate-100">{project.tone}</span>
              </div>
              {project.system_prompt ? (
                <div className="flex gap-2">
                  <span className="text-slate-400 w-24 flex-shrink-0">AI Prompt</span>
                  <span className="text-indigo-300 text-xs font-mono line-clamp-2">{project.system_prompt}</span>
                </div>
              ) : (
                <div className="flex gap-2">
                  <span className="text-slate-400 w-24 flex-shrink-0">AI Prompt</span>
                  <span className="text-slate-600 text-xs italic">Default OnlyWin persona</span>
                </div>
              )}
              {project.context && (
                <div className="flex gap-2">
                  <span className="text-slate-400 w-24 flex-shrink-0">Context</span>
                  <span className="text-slate-100">{project.context}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, icon, highlight }) {
  return (
    <div className={`bg-slate-800 rounded-2xl border p-4 ${highlight ? "border-amber-500/50" : "border-slate-700"}`}>
      <div className="text-2xl mb-1">{icon}</div>
      <div className={`text-2xl font-bold ${highlight ? "text-amber-400" : "text-slate-100"}`}>{value}</div>
      <div className="text-xs text-slate-400 mt-0.5">{label}</div>
    </div>
  );
}

const URGENCY = {
  high: "text-red-400 bg-red-400/10",
  medium: "text-yellow-400 bg-yellow-400/10",
  low: "text-green-400 bg-green-400/10",
};

function AwayLogPanel({ log, onMarkReviewed, onMarkAllReviewed }) {
  const unreviewed = log.filter((l) => !l.reviewed).length;

  return (
    <div className="bg-slate-800 rounded-2xl border border-slate-700 p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-base">🌙</span>
          <h3 className="text-sm font-medium text-slate-200">Away Replies</h3>
          {unreviewed > 0 && (
            <span className="bg-amber-500/20 text-amber-300 text-xs px-2 py-0.5 rounded-full font-medium">
              {unreviewed} to review
            </span>
          )}
        </div>
        {unreviewed > 0 && (
          <button
            onClick={onMarkAllReviewed}
            className="text-xs text-slate-400 hover:text-slate-200 px-3 py-1 rounded-lg hover:bg-slate-700 transition-colors"
          >
            Mark all reviewed
          </button>
        )}
      </div>

      <div className="flex flex-col gap-3 max-h-96 overflow-y-auto">
        {log.map((entry) => (
          <div
            key={entry.id}
            className={`rounded-xl border p-3 transition-opacity ${
              entry.reviewed ? "opacity-50 border-slate-700" : "border-amber-500/30 bg-amber-500/5"
            }`}
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-medium text-slate-200">{entry.chat_name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${URGENCY[entry.urgency] || URGENCY.medium}`}>
                  {entry.urgency}
                </span>
                <span className="text-[10px] text-slate-500 capitalize">{entry.category}</span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-[10px] text-slate-500">
                  {new Date(entry.replied_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </span>
                {!entry.reviewed && (
                  <button
                    onClick={() => onMarkReviewed(entry.id)}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 px-2 py-0.5 rounded hover:bg-indigo-400/10 transition-colors"
                  >
                    Done
                  </button>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex gap-2 text-xs">
                <span className="text-slate-500 w-14 flex-shrink-0">Received</span>
                <span className="text-slate-300 italic">"{entry.incoming_text}"</span>
              </div>
              <div className="flex gap-2 text-xs">
                <span className="text-slate-500 w-14 flex-shrink-0">Sent</span>
                <span className="text-indigo-300">"{entry.reply_text}"</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProjectForm({ title, data, onChange, onSave, onCancel }) {
  const INPUT = "bg-slate-900 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 w-full";
  return (
    <div className="flex flex-col gap-3">
      {title && <h3 className="text-sm font-medium text-slate-200">{title}</h3>}
      <input
        value={data.name}
        onChange={(e) => onChange({ ...data, name: e.target.value })}
        placeholder="Project name"
        className={INPUT}
      />

      {/* AI Behaviour Prompt — the most important field */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-indigo-300">
          AI Behaviour Prompt
          <span className="ml-1 text-slate-500 font-normal">(defines what the bot does in this project)</span>
        </label>
        <textarea
          value={data.system_prompt || ""}
          onChange={(e) => onChange({ ...data, system_prompt: e.target.value })}
          placeholder={`Describe the bot's persona and goal.\n\nExample: You are a friendly sales rep for AcmeCo. Your job is to answer questions about our SaaS product and get people to sign up for a free trial at @AcmeBot. Keep replies short, friendly, in Hinglish.`}
          rows={5}
          className={INPUT + " resize-none font-mono text-xs"}
        />
        <p className="text-[10px] text-slate-600">
          Leave blank to use the default OnlyWin cricket promotion persona.
        </p>
      </div>

      <select
        value={data.tone}
        onChange={(e) => onChange({ ...data, tone: e.target.value })}
        className={INPUT}
      >
        <option value="casual">Casual</option>
        <option value="formal">Formal</option>
        <option value="sales">Sales</option>
        <option value="support">Support</option>
      </select>
      <textarea
        value={data.context}
        onChange={(e) => onChange({ ...data, context: e.target.value })}
        placeholder="Short context note (optional)"
        rows={2}
        className={INPUT + " resize-none"}
      />
      <div className="flex gap-2">
        <button onClick={onCancel} className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-xl py-2.5 text-sm">
          Cancel
        </button>
        <button onClick={onSave} className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl py-2.5 text-sm font-medium">
          Save
        </button>
      </div>
    </div>
  );
}
