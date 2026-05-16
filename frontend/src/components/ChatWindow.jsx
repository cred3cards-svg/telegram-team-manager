import React, { useEffect, useRef, useState } from "react";

export default function ChatWindow({ chat, messages, onSend, isSending }) {
  const [text, setText] = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend() {
    if (!text.trim()) return;
    onSend(text.trim());
    setText("");
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  if (!chat) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
        Select a conversation from the sidebar
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-700 flex items-center gap-3 bg-slate-900">
        <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-sm">
          {chat.type === "group" ? "👥" : "👤"}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-100">{chat.chat_name || chat.chat_id}</div>
          <div className="text-xs text-slate-400 capitalize">{chat.type} · via {chat.phone}</div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
        {messages.length === 0 ? (
          <div className="text-center text-slate-500 text-sm mt-8">No messages yet</div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-slate-700">
        <div className="flex gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKey}
            rows={2}
            placeholder="Type a message or use AI draft..."
            className="flex-1 bg-slate-800 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 resize-none focus:outline-none focus:border-indigo-500 transition-colors placeholder:text-slate-500"
          />
          <button
            onClick={handleSend}
            disabled={isSending || !text.trim()}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl text-sm font-medium transition-colors"
          >
            {isSending ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ msg }) {
  const isOut = msg.is_outgoing;
  const time = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <div className={`flex flex-col ${isOut ? "items-end" : "items-start"} gap-0.5`}>
      {!isOut && (
        <span className="text-xs text-slate-400 ml-1">{msg.sender}</span>
      )}
      <div
        className={`max-w-[72%] px-3.5 py-2 rounded-2xl text-sm leading-relaxed ${
          isOut
            ? "bg-indigo-600 text-white rounded-br-sm"
            : "bg-slate-700 text-slate-100 rounded-bl-sm"
        }`}
      >
        {msg.text}
      </div>
      {time && (
        <span className="text-[10px] text-slate-500 mx-1">{time}</span>
      )}
    </div>
  );
}
