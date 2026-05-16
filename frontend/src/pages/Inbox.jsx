import React, { useState, useEffect, useCallback, useRef } from "react";
import { api, createWebSocket } from "../api";
import ChatWindow from "../components/ChatWindow";
import AIDraftBar from "../components/AIDraftBar";
import AwayModal from "../components/AwayModal";

export default function Inbox({ project }) {
  const [chats, setChats] = useState([]);
  const [selectedChat, setSelectedChat] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState(null);
  const [isDraftLoading, setIsDraftLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [filter, setFilter] = useState("all");
  const wsRef = useRef(null);

  const loadInbox = useCallback(async () => {
    if (!project) return;
    try {
      const data = await api.getInbox(project.id);
      setChats(data);
    } catch (e) {
      console.error(e);
    }
  }, [project]);

  useEffect(() => {
    loadInbox();
  }, [loadInbox]);

  // WebSocket for real-time updates
  useEffect(() => {
    if (!project) return;
    const ws = createWebSocket(project.id, (msg) => {
      if (msg.type === "away_reply_sent") {
        if (
          selectedChat &&
          selectedChat.chat_id === msg.chat_id &&
          selectedChat.account_id === msg.account_id
        ) {
          setMessages((prev) => [
            ...prev,
            { sender: "You", text: msg.text, timestamp: msg.timestamp, is_outgoing: true },
          ]);
        }
        return;
      }
      if (msg.type === "new_message") {
        setChats((prev) => {
          const idx = prev.findIndex(
            (c) => c.chat_id === msg.chat_id && c.account_id === msg.account_id
          );
          if (idx >= 0) {
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              last_message: msg.text,
              unread_count: updated[idx].unread_count + 1,
            };
            return updated;
          }
          return [
            {
              chat_id: msg.chat_id,
              account_id: msg.account_id,
              chat_name: msg.chat_name,
              type: msg.chat_type,
              last_message: msg.text,
              unread_count: 1,
              phone: "",
            },
            ...prev,
          ];
        });

        // If this chat is open, append message and trigger AI draft
        if (
          selectedChat &&
          selectedChat.chat_id === msg.chat_id &&
          selectedChat.account_id === msg.account_id
        ) {
          setMessages((prev) => [
            ...prev,
            {
              sender: msg.sender,
              text: msg.text,
              timestamp: msg.timestamp,
              is_outgoing: false,
            },
          ]);
          triggerDraft(msg.text, msg.message_id);
        }
      }
    });
    wsRef.current = ws;
    return () => ws.close();
  }, [project, selectedChat]);

  const triggerDraft = useCallback(
    async (latestMessage, messageId = null) => {
      if (!project) return;
      setIsDraftLoading(true);
      setDraft(null);
      try {
        const history = messages.slice(-5).map((m) => ({
          sender: m.sender,
          text: m.text,
        }));
        const d = await api.getDraft({
          message_text: latestMessage,
          chat_history: history,
          chat_type: selectedChat?.type || "dm",
          project_context: project.context || "",
          tone: project.tone || "casual",
          message_id: messageId,
          account_id: selectedChat?.account_id || null,
        });
        setDraft(d);
      } catch (e) {
        console.error("AI draft error:", e);
      } finally {
        setIsDraftLoading(false);
      }
    },
    [project, messages, selectedChat]
  );

  async function selectChat(chat) {
    setSelectedChat(chat);
    setDraft(null);
    setMessages([]);
    try {
      const history = await api.getChatHistory(chat.account_id, chat.chat_id);
      setMessages(history);
      // Auto-trigger draft from last incoming message
      const lastIncoming = [...history].reverse().find((m) => !m.is_outgoing);
      if (lastIncoming) triggerDraft(lastIncoming.text);
    } catch (e) {
      console.error(e);
    }
  }

  async function handleSend(text) {
    if (!selectedChat) return;
    setIsSending(true);
    try {
      await api.sendMessage(selectedChat.account_id, selectedChat.chat_id, text);
      setMessages((prev) => [
        ...prev,
        {
          sender: "You",
          text,
          timestamp: new Date().toISOString(),
          is_outgoing: true,
        },
      ]);
      setDraft(null);
    } catch (e) {
      alert(e.message);
    } finally {
      setIsSending(false);
    }
  }

  const filtered = chats.filter((c) => {
    if (filter === "dm") return c.type === "dm";
    if (filter === "groups") return c.type === "group";
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      {/* ── Top bar with Away button ── */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700 bg-slate-900 flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-slate-100">{project?.name || "Inbox"}</h2>
          <div className="flex gap-1">
            {["all", "dm", "groups"].map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-lg text-xs capitalize transition-colors ${
                  filter === f ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        {project && (
          <AwayModal project={project} chats={chats} />
        )}
      </div>

      {/* ── Main 3-column layout ── */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <div className="w-72 flex-shrink-0 border-r border-slate-700 flex flex-col bg-slate-900">
          <div className="flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="text-xs text-slate-500 text-center mt-8 px-4">No conversations yet</p>
            ) : (
              filtered.map((chat) => (
                <ChatListItem
                  key={`${chat.account_id}-${chat.chat_id}`}
                  chat={chat}
                  isSelected={
                    selectedChat?.chat_id === chat.chat_id &&
                    selectedChat?.account_id === chat.account_id
                  }
                  onClick={() => selectChat(chat)}
                />
              ))
            )}
          </div>
        </div>

        {/* Chat window */}
        <div className="flex-1 flex flex-col bg-slate-950">
          <ChatWindow
            chat={selectedChat}
            messages={messages}
            onSend={handleSend}
            isSending={isSending}
          />
        </div>

        {/* AI Draft Panel */}
        <div className="w-72 flex-shrink-0">
          <AIDraftBar
            draft={draft}
            isLoading={isDraftLoading}
            onSend={handleSend}
            onRegenerate={() => {
              const lastIncoming = [...messages].reverse().find((m) => !m.is_outgoing);
              if (lastIncoming) triggerDraft(lastIncoming.text);
            }}
            onDismiss={() => setDraft(null)}
          />
        </div>
      </div>
    </div>
  );
}

function ChatListItem({ chat, isSelected, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-slate-800 hover:bg-slate-800 transition-colors flex items-center gap-3 ${
        isSelected ? "bg-slate-800 border-l-2 border-l-indigo-500" : ""
      }`}
    >
      <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center text-sm flex-shrink-0">
        {chat.type === "group" ? "👥" : "👤"}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-100 truncate">
            {chat.chat_name || chat.chat_id}
          </span>
          {chat.unread_count > 0 && (
            <span className="flex-shrink-0 bg-indigo-600 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center ml-1">
              {chat.unread_count > 9 ? "9+" : chat.unread_count}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500 truncate mt-0.5">{chat.last_message}</p>
      </div>
    </button>
  );
}
