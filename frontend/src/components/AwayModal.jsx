import React, { useState, useEffect } from "react";
import { api } from "../api";

const DURATIONS = [
  { label: "30 min", hours: 0.5 },
  { label: "1 hour", hours: 1 },
  { label: "2 hours", hours: 2 },
  { label: "4 hours", hours: 4 },
  { label: "6 hours", hours: 6 },
];

function fmt(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function AwayModal({ project, chats, onStatusChange }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState({ active: false, seconds_remaining: 0, target_mode: "all", target_chat_ids: [] });
  const [hours, setHours] = useState(1);
  const [targetMode, setTargetMode] = useState("all");
  const [selectedChats, setSelectedChats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!project) return;
    api.awayStatus(project.id).then(s => {
      setStatus(s);
      if (s.active) {
        setTargetMode(s.target_mode);
        setSelectedChats(s.target_chat_ids || []);
      }
    }).catch(() => {});
  }, [project]);

  // Countdown tick
  useEffect(() => {
    if (!status.active) return;
    const id = setInterval(() => {
      setStatus(prev => {
        const next = prev.seconds_remaining - 1;
        if (next <= 0) {
          clearInterval(id);
          onStatusChange?.(false);
          return { ...prev, active: false, seconds_remaining: 0 };
        }
        return { ...prev, seconds_remaining: next };
      });
    }, 1000);
    return () => clearInterval(id);
  }, [status.active, status.away_until]);

  async function handleEnable() {
    setLoading(true);
    try {
      const res = await api.awayEnable(
        project.id,
        hours,
        targetMode,
        targetMode === "selected" ? selectedChats : []
      );
      setStatus({ active: true, away_until: res.away_until, seconds_remaining: res.seconds_remaining, target_mode: targetMode, target_chat_ids: res.target_chat_ids });
      setOpen(false);
      onStatusChange?.(true);
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDisable() {
    setLoading(true);
    try {
      await api.awayDisable(project.id);
      setStatus({ active: false, seconds_remaining: 0, target_mode: "all", target_chat_ids: [] });
      setOpen(false);
      onStatusChange?.(false);
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleChat(key) {
    setSelectedChats(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  }

  const dmChats = chats.filter(c => c.type === "dm");

  return (
    <>
      {/* ── Trigger button ── */}
      {status.active ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30 rounded-xl px-4 py-2 transition-colors"
        >
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          <span className="text-sm font-semibold text-amber-300">Away</span>
          <span className="text-sm font-mono text-amber-400">{fmt(status.seconds_remaining)}</span>
          <span className="text-xs text-amber-500 ml-1">
            {status.target_mode === "all" ? "· All DMs" : `· ${status.target_chat_ids?.length} chat${status.target_chat_ids?.length !== 1 ? "s" : ""}`}
          </span>
        </button>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 border border-slate-600 hover:border-slate-500 rounded-xl px-4 py-2 transition-colors"
        >
          <span className="text-base">🌙</span>
          <span className="text-sm font-semibold text-slate-200">Go Away</span>
        </button>
      )}

      {/* ── Modal ── */}
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />

          <div className="relative bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
              <div className="flex items-center gap-3">
                <span className="text-2xl">🌙</span>
                <div>
                  <h2 className="text-base font-semibold text-slate-100">Away Mode</h2>
                  <p className="text-xs text-slate-400">AI replies automatically while you're away</p>
                </div>
              </div>
              <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-slate-300 text-lg leading-none">✕</button>
            </div>

            <div className="px-6 py-5 flex flex-col gap-6">
              {status.active ? (
                /* ── Active state ── */
                <div className="flex flex-col gap-4">
                  <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-center">
                    <p className="text-3xl font-bold font-mono text-amber-300">{fmt(status.seconds_remaining)}</p>
                    <p className="text-xs text-amber-500 mt-1">remaining</p>
                  </div>
                  <div className="text-sm text-slate-300">
                    <span className="text-slate-400">Auto-replying to: </span>
                    {status.target_mode === "all"
                      ? "All incoming DMs"
                      : `${status.target_chat_ids?.length} selected chat${status.target_chat_ids?.length !== 1 ? "s" : ""}`}
                  </div>
                  <button
                    onClick={handleDisable}
                    disabled={loading}
                    className="w-full bg-amber-500 hover:bg-amber-400 disabled:opacity-40 text-white font-semibold rounded-xl py-3 transition-colors"
                  >
                    I'm Back — Disable Away Mode
                  </button>
                </div>
              ) : (
                /* ── Setup state ── */
                <>
                  {/* Duration */}
                  <div>
                    <label className="text-xs text-slate-400 uppercase tracking-wide mb-3 block">How long?</label>
                    <div className="grid grid-cols-5 gap-2">
                      {DURATIONS.map(d => (
                        <button
                          key={d.hours}
                          onClick={() => setHours(d.hours)}
                          className={`py-2.5 rounded-xl text-sm font-medium transition-colors ${
                            hours === d.hours
                              ? "bg-indigo-600 text-white"
                              : "bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
                          }`}
                        >
                          {d.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Target */}
                  <div>
                    <label className="text-xs text-slate-400 uppercase tracking-wide mb-3 block">Auto-reply for</label>
                    <div className="flex gap-2 mb-4">
                      <button
                        onClick={() => setTargetMode("all")}
                        className={`flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                          targetMode === "all"
                            ? "bg-indigo-600 text-white"
                            : "bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
                        }`}
                      >
                        All DMs
                      </button>
                      <button
                        onClick={() => setTargetMode("selected")}
                        className={`flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                          targetMode === "selected"
                            ? "bg-indigo-600 text-white"
                            : "bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
                        }`}
                      >
                        Selected Chats
                      </button>
                    </div>

                    {targetMode === "selected" && (
                      <div className="flex flex-col gap-1.5 max-h-52 overflow-y-auto pr-1">
                        {dmChats.length === 0 ? (
                          <p className="text-xs text-slate-500 text-center py-4">No DM chats found in inbox</p>
                        ) : (
                          <>
                            <div className="flex justify-between items-center mb-1">
                              <span className="text-xs text-slate-500">{selectedChats.length} selected</span>
                              <button
                                onClick={() => {
                                  const allKeys = dmChats.map(c => `${c.account_id}:${c.chat_id}`);
                                  setSelectedChats(selectedChats.length === allKeys.length ? [] : allKeys);
                                }}
                                className="text-xs text-indigo-400 hover:text-indigo-300"
                              >
                                {selectedChats.length === dmChats.length ? "Deselect all" : "Select all"}
                              </button>
                            </div>
                            {dmChats.map(chat => {
                              const key = `${chat.account_id}:${chat.chat_id}`;
                              const checked = selectedChats.includes(key);
                              return (
                                <button
                                  key={key}
                                  onClick={() => toggleChat(key)}
                                  className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-colors ${
                                    checked
                                      ? "bg-indigo-600/20 border border-indigo-500/50"
                                      : "bg-slate-800 border border-slate-700 hover:border-slate-500"
                                  }`}
                                >
                                  <div className={`w-4 h-4 rounded flex-shrink-0 flex items-center justify-center border ${
                                    checked ? "bg-indigo-600 border-indigo-600" : "border-slate-500"
                                  }`}>
                                    {checked && <span className="text-white text-[10px] leading-none">✓</span>}
                                  </div>
                                  <div className="min-w-0">
                                    <p className="text-sm text-slate-100 truncate">{chat.chat_name || chat.chat_id}</p>
                                    <p className="text-xs text-slate-500 truncate">{chat.phone}</p>
                                  </div>
                                </button>
                              );
                            })}
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  <button
                    onClick={handleEnable}
                    disabled={loading || (targetMode === "selected" && selectedChats.length === 0)}
                    className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded-xl py-3 transition-colors flex items-center justify-center gap-2"
                  >
                    <span>🌙</span>
                    <span>{loading ? "Activating..." : `Go Away for ${DURATIONS.find(d => d.hours === hours)?.label}`}</span>
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
