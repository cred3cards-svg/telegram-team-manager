import React, { useState, useEffect, useRef } from "react";
import { api } from "../api";

const PRESETS = [
  { label: "30 min", hours: 0.5 },
  { label: "1 hr", hours: 1 },
  { label: "2 hr", hours: 2 },
  { label: "4 hr", hours: 4 },
  { label: "6 hr", hours: 6 },
];

function formatCountdown(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function AwayButton({ projectId }) {
  const [status, setStatus] = useState({ active: false, seconds_remaining: 0 });
  const [showPicker, setShowPicker] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef(null);
  const pickerRef = useRef(null);

  async function fetchStatus() {
    try {
      const s = await api.awayStatus(projectId);
      setStatus(s);
    } catch (_) {}
  }

  useEffect(() => {
    fetchStatus();
  }, [projectId]);

  // Tick countdown locally
  useEffect(() => {
    clearInterval(timerRef.current);
    if (status.active && status.seconds_remaining > 0) {
      timerRef.current = setInterval(() => {
        setStatus((prev) => {
          const next = prev.seconds_remaining - 1;
          if (next <= 0) {
            clearInterval(timerRef.current);
            return { active: false, seconds_remaining: 0 };
          }
          return { ...prev, seconds_remaining: next };
        });
      }, 1000);
    }
    return () => clearInterval(timerRef.current);
  }, [status.active, status.away_until]);

  // Close picker on outside click
  useEffect(() => {
    function handle(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        setShowPicker(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  async function handleEnable(hours) {
    setLoading(true);
    setShowPicker(false);
    try {
      const res = await api.awayEnable(projectId, hours);
      setStatus({ active: true, away_until: res.away_until, seconds_remaining: res.seconds_remaining });
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleDisable() {
    setLoading(true);
    try {
      await api.awayDisable(projectId);
      setStatus({ active: false, seconds_remaining: 0 });
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (status.active) {
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-2 bg-amber-500/20 border border-amber-500/40 rounded-xl px-3 py-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          <span className="text-xs font-medium text-amber-300">Away</span>
          <span className="text-xs text-amber-400 font-mono">
            {formatCountdown(status.seconds_remaining)}
          </span>
        </div>
        <button
          onClick={handleDisable}
          disabled={loading}
          className="text-xs text-slate-400 hover:text-slate-200 px-2 py-1.5 rounded-lg hover:bg-slate-700 transition-colors"
        >
          Back
        </button>
      </div>
    );
  }

  return (
    <div className="relative" ref={pickerRef}>
      <button
        onClick={() => setShowPicker((v) => !v)}
        disabled={loading}
        className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-slate-500 text-slate-300 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors"
      >
        <span>🌙</span>
        <span>Go Away</span>
      </button>

      {showPicker && (
        <div className="absolute top-full mt-2 left-0 z-50 bg-slate-800 border border-slate-600 rounded-2xl shadow-2xl p-3 min-w-[160px]">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-2 px-1">
            Away for how long?
          </p>
          <div className="flex flex-col gap-1">
            {PRESETS.map((p) => (
              <button
                key={p.hours}
                onClick={() => handleEnable(p.hours)}
                className="text-left px-3 py-1.5 rounded-lg text-sm text-slate-200 hover:bg-indigo-600 hover:text-white transition-colors"
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-slate-500 mt-2 px-1">
            AI will auto-reply to DMs
          </p>
        </div>
      )}
    </div>
  );
}
