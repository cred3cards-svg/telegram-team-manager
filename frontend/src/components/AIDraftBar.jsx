import React, { useState, useEffect } from "react";

const URGENCY_CONFIG = {
  high: { label: "High", color: "text-red-400", dot: "bg-red-400", icon: "🔴" },
  medium: { label: "Medium", color: "text-yellow-400", dot: "bg-yellow-400", icon: "🟡" },
  low: { label: "Low", color: "text-green-400", dot: "bg-green-400", icon: "🟢" },
};

const CATEGORY_ICONS = {
  support: "🛠",
  sales: "💼",
  general: "💬",
  spam: "🚫",
};

export default function AIDraftBar({ draft, onSend, onRegenerate, onDismiss, isLoading }) {
  const [editedText, setEditedText] = useState(draft?.draft || "");

  useEffect(() => {
    setEditedText(draft?.draft || "");
  }, [draft?.draft]);

  const urgency = URGENCY_CONFIG[draft?.urgency] || URGENCY_CONFIG.medium;
  const categoryIcon = CATEGORY_ICONS[draft?.category] || "💬";

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-700">
      <div className="p-4 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-100">AI Draft</span>
          <span className="text-xs bg-indigo-600/30 text-indigo-300 px-2 py-0.5 rounded-full">Claude</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <div className="flex flex-col gap-3">
            <div className="h-4 bg-slate-700 rounded animate-pulse w-3/4" />
            <div className="h-4 bg-slate-700 rounded animate-pulse w-full" />
            <div className="h-4 bg-slate-700 rounded animate-pulse w-2/3" />
            <p className="text-xs text-slate-500 mt-2">Generating draft...</p>
          </div>
        ) : draft ? (
          <div className="flex flex-col gap-4">
            <div>
              <label className="text-xs text-slate-400 uppercase tracking-wide mb-2 block">
                Suggested Reply
              </label>
              <textarea
                value={editedText}
                onChange={(e) => setEditedText(e.target.value)}
                rows={5}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg p-3 text-sm text-slate-100 resize-none focus:outline-none focus:border-indigo-500 transition-colors"
                placeholder="AI suggested reply..."
              />
            </div>

            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1.5">
                <span>{categoryIcon}</span>
                <span className="text-slate-400 capitalize">{draft.category}</span>
              </div>
              <div className="w-px h-3 bg-slate-600" />
              <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${urgency.dot}`} />
                <span className={urgency.color}>{urgency.label} urgency</span>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <button
                onClick={() => onSend(editedText)}
                className="w-full bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg py-2 text-sm font-medium transition-colors"
              >
                Edit & Send
              </button>
              <button
                onClick={onRegenerate}
                className="w-full bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg py-2 text-sm transition-colors"
              >
                Regenerate
              </button>
              <button
                onClick={onDismiss}
                className="w-full text-slate-500 hover:text-slate-300 rounded-lg py-2 text-sm transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center gap-3">
            <div className="text-3xl">✨</div>
            <p className="text-sm text-slate-400">
              Select a chat and receive a message to see an AI-suggested reply
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
