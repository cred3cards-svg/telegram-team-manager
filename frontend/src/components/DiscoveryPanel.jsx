import React, { useState, useEffect } from "react";
import { api } from "../api";

const CATEGORIES = ["all", "cricket", "bollywood", "adult", "finance", "memes", "general"];

const CAT_COLORS = {
  cricket:  "bg-green-500/20 text-green-300",
  bollywood:"bg-pink-500/20 text-pink-300",
  adult:    "bg-red-500/20 text-red-300",
  finance:  "bg-yellow-500/20 text-yellow-300",
  memes:    "bg-purple-500/20 text-purple-300",
  general:  "bg-slate-500/20 text-slate-300",
};

export default function DiscoveryPanel({ accounts = [], project = null }) {
  const [groups, setGroups] = useState([]);
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [joining, setJoining] = useState({});   // group_id -> bool
  const [selectedAccount, setSelectedAccount] = useState(accounts[0]?.id || null);
  const hasAccounts = accounts.length > 0;

  async function loadGroups() {
    setLoading(true);
    try {
      const data = await api.getSuggestedGroups(category, project?.id || 0);
      setGroups(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadGroups(); }, [category, project?.id]);

  async function handleScanNow() {
    if (!selectedAccount) return;
    setScanning(true);
    try {
      await api.runDiscoveryNow(selectedAccount);
      // Poll after 30s for results
      setTimeout(loadGroups, 30000);
    } catch (e) {
      alert(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function handleJoin(group) {
    if (!selectedAccount) return;
    setJoining((p) => ({ ...p, [group.group_id]: true }));
    try {
      await api.joinSuggestedGroup(selectedAccount, group.group_id);
      // Update in-place so the row shows "Joined ✓" immediately without re-fetch
      setGroups((prev) =>
        prev.map((g) => g.group_id === group.group_id ? { ...g, is_joined: true } : g)
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setJoining((p) => ({ ...p, [group.group_id]: false }));
    }
  }

  return (
    <div className="bg-slate-800 rounded-2xl border border-slate-700 p-5 mb-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-base">🔍</span>
          <h3 className="text-sm font-medium text-slate-200">Suggested Groups</h3>
          <span className="text-xs text-slate-500">India • 1000+ members • Auto-discovered</span>
        </div>
        <div className="flex items-center gap-2">
          {accounts.length > 1 && (
            <select
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(Number(e.target.value))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.phone}</option>
              ))}
            </select>
          )}
          <button
            onClick={handleScanNow}
            disabled={scanning || !hasAccounts}
            title={!hasAccounts ? "Add an account first to scan" : ""}
            className="text-xs px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg transition-colors"
          >
            {scanning ? "Scanning..." : "Scan Now"}
          </button>
        </div>
      </div>

      {/* Category filter */}
      <div className="flex gap-1.5 flex-wrap mb-4">
        {CATEGORIES.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`px-3 py-1 rounded-lg text-xs capitalize transition-colors ${
              category === c
                ? "bg-indigo-600 text-white"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      {/* Groups list */}
      {loading ? (
        <p className="text-xs text-slate-500 text-center py-6">Loading...</p>
      ) : groups.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-xs text-slate-500 mb-3">No groups discovered yet.</p>
          <p className="text-xs text-slate-600">Click "Scan Now" to start — runs automatically every 6 hours.</p>
        </div>
      ) : (
        <>
          {!hasAccounts && (
            <p className="text-xs text-amber-400/80 bg-amber-400/10 rounded-lg px-3 py-2 mb-3">
              Add an account in the Accounts tab to join groups or trigger a scan.
              Discovered groups are saved and will appear here automatically.
            </p>
          )}
          <div className="flex flex-col gap-2 max-h-[480px] overflow-y-auto pr-1">
            {groups.map((g) => (
              <div
                key={g.group_id}
                className="flex items-center justify-between gap-3 bg-slate-900 rounded-xl px-4 py-3 border border-slate-700/50"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-medium text-slate-100 truncate">{g.name}</span>
                    <span className={`flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded capitalize ${CAT_COLORS[g.category] || CAT_COLORS.general}`}>
                      {g.category}
                    </span>
                  </div>
                  {g.description && (
                    <p className="text-xs text-slate-500 truncate mb-1">{g.description}</p>
                  )}
                  <div className="flex items-center gap-3 text-[10px] text-slate-500">
                    <span>👥 {g.members?.toLocaleString()} members</span>
                    {g.online_members > 0 && (
                      <span className="text-green-400">🟢 {g.online_members?.toLocaleString()} online</span>
                    )}
                    {g.username && (
                      <span className="text-slate-600">@{g.username}</span>
                    )}
                  </div>
                </div>

                <button
                  onClick={() => !g.is_joined && handleJoin(g)}
                  disabled={joining[g.group_id] || g.is_joined || !hasAccounts}
                  title={!hasAccounts ? "Add an account to join" : g.is_joined ? "Already in your project" : ""}
                  className={`flex-shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                    g.is_joined
                      ? "bg-green-600/20 text-green-400 cursor-default"
                      : "bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
                  }`}
                >
                  {g.is_joined ? "Joined ✓" : joining[g.group_id] ? "Joining..." : "Join"}
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
