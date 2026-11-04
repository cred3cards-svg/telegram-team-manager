import React, { useState, useEffect, useCallback } from "react";
import { api } from "../api";

const autoJoinApi = {
  status: (project_id) =>
    fetch(`${process.env.REACT_APP_API_URL || ""}/auto-join/status?project_id=${project_id}`)
      .then((r) => r.json()),
  joined: (project_id) =>
    fetch(`${process.env.REACT_APP_API_URL || ""}/auto-join/joined?project_id=${project_id}`)
      .then((r) => r.json()),
  suggested: (project_id) =>
    fetch(`${process.env.REACT_APP_API_URL || ""}/auto-join/suggested?project_id=${project_id}&limit=100`)
      .then((r) => r.json()),
  runNow: (project_id) =>
    fetch(`${process.env.REACT_APP_API_URL || ""}/auto-join/run-now?project_id=${project_id}`, { method: "POST" })
      .then((r) => r.json()),
};

function ScoreBadge({ score, leftAt }) {
  if (leftAt) return <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-400">Left</span>;
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const color = score >= 0.5 ? "text-green-400 bg-green-500/15" : score >= 0.28 ? "text-yellow-400 bg-yellow-500/15" : "text-red-400 bg-red-500/15";
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${color}`}>
      {pct}% human
    </span>
  );
}

export default function AutoJoin({ project }) {
  const [tab, setTab] = useState("joined"); // joined | suggested
  const [status, setStatus] = useState(null);
  const [joined, setJoined] = useState([]);
  const [suggested, setSuggested] = useState([]);
  const [loading, setLoading] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [triggered, setTriggered] = useState(false);

  const load = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    try {
      const [s, j, sg] = await Promise.all([
        autoJoinApi.status(project.id),
        autoJoinApi.joined(project.id),
        autoJoinApi.suggested(project.id),
      ]);
      setStatus(s);
      setJoined(j);
      setSuggested(sg);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => { load(); }, [load]);

  async function handleRunNow() {
    setTriggering(true);
    try {
      await autoJoinApi.runNow(project.id);
      setTriggered(true);
      setTimeout(() => setTriggered(false), 4000);
      setTimeout(() => load(), 15000); // refresh after 15s
    } catch (e) {
      alert(e.message);
    } finally {
      setTriggering(false);
    }
  }

  const activeJoined = joined.filter((g) => !g.left_at);
  const leftGroups = joined.filter((g) => g.left_at);

  return (
    <div className="p-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Auto Join</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Automatically joins Indian groups, scores activity, leaves spammy ones after 2 days
          </p>
        </div>
        <button
          onClick={handleRunNow}
          disabled={triggering || triggered}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors font-medium"
        >
          {triggered ? "✓ Triggered!" : triggering ? "Triggering..." : "▶ Run Now"}
        </button>
      </div>

      {/* Stats */}
      {status && (
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: "Suggested", value: status.total_suggested, color: "text-slate-300" },
            { label: "Pending", value: status.pending, color: "text-indigo-400" },
            { label: "Active", value: status.joined, color: "text-green-400" },
            { label: "Left", value: status.left, color: "text-red-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-slate-800 rounded-xl border border-slate-700 p-3 text-center">
              <div className={`text-xl font-bold ${color}`}>{value}</div>
              <div className="text-[11px] text-slate-500 mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-slate-800 rounded-xl p-1 w-fit">
        {[
          { id: "joined", label: `Active (${activeJoined.length})` },
          { id: "left", label: `Left (${leftGroups.length})` },
          { id: "suggested", label: `Pending (${suggested.length})` },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`text-xs px-3 py-1.5 rounded-lg transition-colors font-medium ${
              tab === t.id
                ? "bg-indigo-600 text-white"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="text-center py-10 text-slate-500">
          <div className="text-2xl mb-2 animate-pulse">🔄</div>
          <p className="text-sm">Loading...</p>
        </div>
      )}

      {/* Active joined groups */}
      {!loading && tab === "joined" && (
        <div className="flex flex-col gap-1.5">
          {activeJoined.length === 0 ? (
            <div className="text-center py-10 text-slate-500">
              <p className="text-2xl mb-2">🤖</p>
              <p className="text-sm">No auto-joined groups yet</p>
              <p className="text-xs mt-1 text-slate-600">
                The join loop runs every 6h (first run 90s after boot).
                Click "Run Now" to trigger immediately.
              </p>
            </div>
          ) : (
            activeJoined.map((g) => (
              <GroupRow key={g.id} g={g} />
            ))
          )}
        </div>
      )}

      {/* Left groups */}
      {!loading && tab === "left" && (
        <div className="flex flex-col gap-1.5">
          {leftGroups.length === 0 ? (
            <p className="text-center text-xs text-slate-600 py-8">No groups left yet</p>
          ) : (
            leftGroups.map((g) => <GroupRow key={g.id} g={g} />)
          )}
        </div>
      )}

      {/* Pending suggested */}
      {!loading && tab === "suggested" && (
        <div className="flex flex-col gap-1.5">
          {suggested.length === 0 ? (
            <p className="text-center text-xs text-slate-600 py-8">
              No pending groups — all have been joined or none discovered yet
            </p>
          ) : (
            suggested.map((g) => (
              <div
                key={g.group_id}
                className="flex items-center gap-3 px-4 py-2.5 bg-slate-800 rounded-xl border border-slate-700"
              >
                <span className="text-base flex-shrink-0">👥</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-slate-100 truncate font-medium">{g.name}</div>
                  <div className="text-[11px] text-slate-500 flex gap-2">
                    {g.username && <span>@{g.username}</span>}
                    {g.members > 0 && <span>{g.members.toLocaleString()} members</span>}
                    <span className="text-slate-600">{g.category}</span>
                  </div>
                </div>
                <span className="text-[11px] text-slate-600 flex-shrink-0">queued</span>
              </div>
            ))
          )}
        </div>
      )}

      {/* How it works */}
      <div className="mt-6 bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
        <p className="text-xs font-medium text-slate-400 mb-2">How it works</p>
        <ul className="text-xs text-slate-500 space-y-1">
          <li>• <span className="text-slate-400">Join loop</span> — every 6h, joins up to 5 groups per account from the discovery queue</li>
          <li>• <span className="text-slate-400">Eval loop</span> — every 1h, checks groups joined 2+ days ago</li>
          <li>• <span className="text-green-500">≥28% unique senders</span> → keep forever (real humans)</li>
          <li>• <span className="text-red-400">&lt;28% unique senders</span> → send final plug, then leave (spam)</li>
        </ul>
      </div>
    </div>
  );
}

function GroupRow({ g }) {
  const joinedDate = g.joined_at ? new Date(g.joined_at).toLocaleDateString("en-IN") : "";
  const leftDate = g.left_at ? new Date(g.left_at).toLocaleDateString("en-IN") : "";

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-slate-800 rounded-xl border border-slate-700">
      <span className="text-base flex-shrink-0">{g.left_at ? "🚪" : "👥"}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm text-slate-100 truncate font-medium">{g.group_name || g.group_id}</div>
        <div className="text-[11px] text-slate-500 flex gap-2 flex-wrap">
          {g.username && <span>@{g.username}</span>}
          {g.phone && <span>{g.phone.slice(-4)}</span>}
          {g.category && <span className="text-slate-600">{g.category}</span>}
          {joinedDate && <span>joined {joinedDate}</span>}
          {leftDate && <span>left {leftDate}</span>}
        </div>
      </div>
      <ScoreBadge score={g.human_score} leftAt={g.left_at} />
    </div>
  );
}
