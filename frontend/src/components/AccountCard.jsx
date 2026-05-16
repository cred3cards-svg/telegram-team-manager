import React from "react";
import { api } from "../api";

const STATUS_COLORS = {
  active: "bg-green-500",
  pending: "bg-yellow-400",
  error: "bg-red-500",
};

export default function AccountCard({ account, onRemove, onSync }) {
  const [syncing, setSyncing] = React.useState(false);
  const [syncMsg, setSyncMsg] = React.useState("");
  const [showPersona, setShowPersona] = React.useState(false);
  const [personality, setPersonality] = React.useState("");
  const [jobDescription, setJobDescription] = React.useState("");
  const [personaLoading, setPersonaLoading] = React.useState(false);
  const [personaSaved, setPersonaSaved] = React.useState(false);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const result = await onSync(account.id);
      setSyncMsg(`✓ ${result.chats_found} chats synced`);
    } catch (e) {
      setSyncMsg(`✗ ${e.message}`);
    } finally {
      setSyncing(false);
    }
  }

  async function handleOpenPersona() {
    if (!showPersona) {
      try {
        const data = await api.getPersona(account.id);
        setPersonality(data.personality || "");
        setJobDescription(data.job_description || "");
      } catch (_) {}
    }
    setShowPersona((v) => !v);
    setPersonaSaved(false);
  }

  async function handleSavePersona() {
    setPersonaLoading(true);
    setPersonaSaved(false);
    try {
      await api.updatePersona(account.id, personality, jobDescription);
      setPersonaSaved(true);
      setTimeout(() => setPersonaSaved(false), 2000);
    } catch (e) {
      alert(e.message);
    } finally {
      setPersonaLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 p-3 bg-slate-800 rounded-xl border border-slate-700 hover:border-slate-500 transition-colors">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-indigo-600 flex items-center justify-center font-semibold text-sm">
            {account.phone.slice(-4)}
          </div>
          <div>
            <div className="text-sm font-medium text-slate-100">{account.phone}</div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`w-1.5 h-1.5 rounded-full ${STATUS_COLORS[account.status] || "bg-slate-500"}`} />
              <span className="text-xs text-slate-400 capitalize">{account.status}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleOpenPersona}
            className={`text-xs px-2 py-1 rounded transition-colors ${
              showPersona
                ? "bg-violet-600 text-white"
                : "text-violet-400 hover:text-violet-300 hover:bg-violet-400/10"
            }`}
          >
            Persona
          </button>
          {account.status === "active" && (
            <button
              onClick={handleSync}
              disabled={syncing}
              className="text-indigo-400 hover:text-indigo-300 disabled:opacity-40 transition-colors text-xs px-2 py-1 rounded hover:bg-indigo-400/10"
            >
              {syncing ? "Syncing..." : "Sync"}
            </button>
          )}
          <button
            onClick={() => onRemove(account.id)}
            className="text-slate-500 hover:text-red-400 transition-colors text-xs px-2 py-1 rounded hover:bg-red-400/10"
          >
            Remove
          </button>
        </div>
      </div>

      {syncMsg && (
        <p className={`text-xs px-1 ${syncMsg.startsWith("✓") ? "text-green-400" : "text-red-400"}`}>
          {syncMsg}
        </p>
      )}

      {showPersona && (
        <div className="mt-1 flex flex-col gap-2 border-t border-slate-700 pt-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 font-medium">Job / Role</label>
            <input
              type="text"
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              placeholder="e.g. Sales rep, Customer support lead, Tech founder"
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 font-medium">Personality & Style</label>
            <textarea
              rows={3}
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              placeholder="e.g. Friendly and concise. Uses casual language. Gets to the point fast. Occasional humour."
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 resize-none"
            />
          </div>
          <button
            onClick={handleSavePersona}
            disabled={personaLoading}
            className="self-end px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs rounded-lg transition-colors"
          >
            {personaSaved ? "Saved!" : personaLoading ? "Saving..." : "Save Persona"}
          </button>
        </div>
      )}
    </div>
  );
}
