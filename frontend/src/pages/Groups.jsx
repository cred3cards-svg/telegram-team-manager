import React, { useState, useEffect, useCallback } from "react";
import { api } from "../api";

export default function Groups({ project }) {
  const [accountGroups, setAccountGroups] = useState([]); // [{account_id, phone, groups:[]}]
  const [loading, setLoading] = useState(false);
  const [leavingGroup, setLeavingGroup] = useState({}); // "accId-groupId" -> bool
  const [leavingAll, setLeavingAll] = useState({});     // accId -> bool
  const [nuking, setNuking] = useState({});             // accId -> bool
  const [groupLink, setGroupLink] = useState("");
  const [joinAccountId, setJoinAccountId] = useState(null);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState("");

  const loadLive = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    try {
      const data = await api.listGroupsLive(project.id);
      setAccountGroups(data);
      // Auto-select first account for join if none selected
      if (!joinAccountId && data.length > 0) setJoinAccountId(data[0].account_id);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [project]);

  useEffect(() => { loadLive(); }, [loadLive]);

  async function handleLeave(accountId, groupId) {
    const key = `${accountId}-${groupId}`;
    setLeavingGroup((p) => ({ ...p, [key]: true }));
    try {
      await api.leaveGroup(accountId, groupId);
      setAccountGroups((prev) =>
        prev.map((a) =>
          a.account_id === accountId
            ? { ...a, groups: a.groups.filter((g) => g.group_id !== groupId) }
            : a
        )
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setLeavingGroup((p) => ({ ...p, [key]: false }));
    }
  }

  async function handleLeaveAll(accountId) {
    if (!window.confirm("Leave ALL groups for this account? This cannot be undone.")) return;
    setLeavingAll((p) => ({ ...p, [accountId]: true }));
    try {
      await api.leaveAllGroups(accountId, project.id);
      setAccountGroups((prev) =>
        prev.map((a) => a.account_id === accountId ? { ...a, groups: [] } : a)
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setLeavingAll((p) => ({ ...p, [accountId]: false }));
    }
  }

  async function handleNuke(accountId, phone) {
    const confirmed = window.confirm(
      `☢️ NUKE "${phone}"?\n\nThis will:\n• Delete ALL messages sent by this account in every group\n• Leave every group\n\nThis CANNOT be undone.`
    );
    if (!confirmed) return;
    setNuking((p) => ({ ...p, [accountId]: true }));
    try {
      const result = await api.nukeAccount(accountId, project.id);
      alert(`Done. Left ${result.groups} groups, deleted ${result.messages_deleted} messages.${result.failed.length ? `\n${result.failed.length} errors.` : ""}`);
      setAccountGroups((prev) =>
        prev.map((a) => a.account_id === accountId ? { ...a, groups: [] } : a)
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setNuking((p) => ({ ...p, [accountId]: false }));
    }
  }

  async function handleJoin() {
    if (!joinAccountId || !groupLink.trim()) return;
    setJoinError("");
    setJoining(true);
    try {
      await api.joinGroup(joinAccountId, groupLink.trim());
      setGroupLink("");
      await loadLive(); // refresh live
    } catch (e) {
      setJoinError(e.message);
    } finally {
      setJoining(false);
    }
  }

  const totalGroups = accountGroups.reduce((s, a) => s + a.groups.length, 0);

  return (
    <div className="p-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Joined Groups</h2>
          {!loading && (
            <p className="text-xs text-slate-500 mt-0.5">
              {totalGroups} groups across {accountGroups.length} accounts — live from Telegram
            </p>
          )}
        </div>
        <button
          onClick={loadLive}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-lg transition-colors"
        >
          <span className={loading ? "animate-spin" : ""}>↻</span>
          {loading ? "Syncing..." : "Refresh"}
        </button>
      </div>

      {/* Join Group */}
      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-4 mb-6">
        <h3 className="text-sm font-medium text-slate-200 mb-3">Join a Group</h3>
        <div className="flex gap-2 mb-2">
          <select
            value={joinAccountId || ""}
            onChange={(e) => setJoinAccountId(Number(e.target.value))}
            className="bg-slate-900 border border-slate-600 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            {accountGroups.map((a) => (
              <option key={a.account_id} value={a.account_id}>{a.phone}</option>
            ))}
          </select>
          <input
            type="text"
            value={groupLink}
            onChange={(e) => setGroupLink(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleJoin()}
            placeholder="https://t.me/groupname or +invitehash"
            className="flex-1 bg-slate-900 border border-slate-600 rounded-xl px-4 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 placeholder:text-slate-500"
          />
          <button
            onClick={handleJoin}
            disabled={joining || !groupLink.trim() || !joinAccountId}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-xl px-4 py-2 text-sm font-medium transition-colors"
          >
            {joining ? "Joining..." : "Join"}
          </button>
        </div>
        {joinError && (
          <p className="text-xs text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{joinError}</p>
        )}
      </div>

      {/* Loading state */}
      {loading && (
        <div className="text-center py-12">
          <div className="text-2xl mb-2 animate-pulse">📡</div>
          <p className="text-sm text-slate-400">Fetching live groups from Telegram...</p>
        </div>
      )}

      {/* Account sections */}
      {!loading && accountGroups.map((acc) => (
        <div key={acc.account_id} className="mb-6">
          {/* Account header */}
          <div className="flex items-center justify-between mb-2 px-1">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-indigo-700 flex items-center justify-center text-xs font-semibold text-white">
                {acc.phone.slice(-4)}
              </div>
              <span className="text-sm font-medium text-slate-200">{acc.phone}</span>
              <span className="text-xs text-slate-500">{acc.groups.length} groups</span>
            </div>
            <div className="flex items-center gap-2">
              {acc.groups.length > 0 && (
                <button
                  onClick={() => handleLeaveAll(acc.account_id)}
                  disabled={leavingAll[acc.account_id] || nuking[acc.account_id]}
                  className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40 px-3 py-1 rounded-lg hover:bg-red-400/10 transition-colors border border-red-400/20"
                >
                  {leavingAll[acc.account_id] ? "Leaving..." : "Leave All"}
                </button>
              )}
              <button
                onClick={() => handleNuke(acc.account_id, acc.phone)}
                disabled={nuking[acc.account_id] || leavingAll[acc.account_id]}
                title="Delete all messages + leave all groups"
                className="text-xs text-orange-500 hover:text-orange-400 disabled:opacity-40 px-3 py-1 rounded-lg hover:bg-orange-500/10 transition-colors border border-orange-500/30 font-medium"
              >
                {nuking[acc.account_id] ? "Nuking..." : "☢ Nuke"}
              </button>
            </div>
          </div>

          {/* Error */}
          {acc.error && (
            <p className="text-xs text-amber-400 bg-amber-400/10 rounded-lg px-3 py-2 mb-2">
              ⚠ Could not fetch live groups: {acc.error}
            </p>
          )}

          {/* Groups list */}
          {acc.groups.length === 0 ? (
            <p className="text-xs text-slate-600 px-1 py-3 text-center border border-dashed border-slate-700 rounded-xl">
              No groups joined on this account
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {acc.groups.map((g) => {
                const key = `${acc.account_id}-${g.group_id}`;
                return (
                  <div
                    key={g.group_id}
                    className="flex items-center gap-3 px-4 py-2.5 bg-slate-800 rounded-xl border border-slate-700 hover:border-slate-600 transition-colors"
                  >
                    <span className="text-base flex-shrink-0">👥</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-100 truncate font-medium">
                        {g.group_name}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-slate-500">
                        {g.username && <span>@{g.username}</span>}
                        {g.members > 0 && <span>{g.members.toLocaleString()} members</span>}
                      </div>
                    </div>
                    <button
                      onClick={() => handleLeave(acc.account_id, g.group_id)}
                      disabled={leavingGroup[key]}
                      className="flex-shrink-0 text-xs text-slate-500 hover:text-red-400 disabled:opacity-40 px-3 py-1 rounded-lg hover:bg-red-400/10 transition-colors"
                    >
                      {leavingGroup[key] ? "Leaving..." : "Leave"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}

      {/* Empty state */}
      {!loading && accountGroups.length === 0 && (
        <div className="text-center py-12 text-slate-500">
          <p className="text-2xl mb-2">📭</p>
          <p className="text-sm">No active accounts found for this project.</p>
          <p className="text-xs mt-1">Add accounts in the Accounts tab first.</p>
        </div>
      )}
    </div>
  );
}
