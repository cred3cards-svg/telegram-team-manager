import React, { useState, useEffect, useRef } from "react";
import { api } from "../api";
import AccountCard from "../components/AccountCard";

const METHODS = [
  { id: "otp", label: "Phone + OTP", icon: "📱" },
  { id: "session", label: "Session String", icon: "🔑" },
  { id: "tdata", label: "TData Folder", icon: "📁" },
];

export default function Accounts({ project }) {
  const [accounts, setAccounts] = useState([]);
  const [method, setMethod] = useState("otp");

  async function loadAccounts() {
    if (!project) return;
    try {
      setAccounts(await api.listAccounts(project.id));
    } catch (e) {
      console.error(e);
    }
  }

  useEffect(() => {
    loadAccounts();
  }, [project]);

  async function handleRemove(id) {
    if (!window.confirm("Remove this account?")) return;
    try {
      await api.removeAccount(id);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      alert(e.message);
    }
  }

  return (
    <div className="p-6 max-w-xl">
      <h2 className="text-lg font-semibold text-slate-100 mb-6">Telegram Accounts</h2>

      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-5 mb-6">
        <h3 className="text-sm font-medium text-slate-200 mb-4">Add Account</h3>

        {/* Method selector */}
        <div className="flex gap-1 mb-5 bg-slate-900 rounded-xl p-1">
          {METHODS.map((m) => (
            <button
              key={m.id}
              onClick={() => setMethod(m.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                method === m.id
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>{m.icon}</span>
              <span className="hidden sm:inline">{m.label}</span>
            </button>
          ))}
        </div>

        {method === "otp" && (
          <OTPForm projectId={project?.id} onSuccess={loadAccounts} />
        )}
        {method === "session" && (
          <SessionForm projectId={project?.id} onSuccess={loadAccounts} />
        )}
        {method === "tdata" && (
          <TDataForm projectId={project?.id} onSuccess={loadAccounts} />
        )}
      </div>

      {/* Accounts list */}
      <div className="flex flex-col gap-3">
        {accounts.length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-8">
            No accounts yet. Add one above.
          </p>
        ) : (
          accounts.map((acc) => (
            <AccountCard
              key={acc.id}
              account={acc}
              onRemove={handleRemove}
              onSync={api.syncAccount}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── Method 1: OTP ─────────────────────────────────────────────────────────────

function OTPForm({ projectId, onSuccess }) {
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [step, setStep] = useState("idle");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSend() {
    setError("");
    setLoading(true);
    try {
      await api.addAccount(phone, projectId);
      setStep("otp");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify() {
    setError("");
    setLoading(true);
    try {
      await api.verifyAccount(phone, otp, password);
      setStep("idle");
      setPhone(""); setOtp(""); setPassword("");
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {step === "idle" ? (
        <>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+91 9876543210"
            className={INPUT}
          />
          <button onClick={handleSend} disabled={loading || !phone.trim()} className={BTN_PRIMARY}>
            {loading ? "Sending OTP..." : "Send OTP"}
          </button>
        </>
      ) : (
        <>
          <p className="text-xs text-slate-400">
            OTP sent to <strong className="text-slate-200">{phone}</strong>
          </p>
          <input
            type="text"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            placeholder="Enter OTP"
            maxLength={6}
            className={INPUT + " tracking-widest"}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="2FA password (if enabled)"
            className={INPUT}
          />
          <div className="flex gap-2">
            <button onClick={() => { setStep("idle"); setError(""); }} className={BTN_SECONDARY}>Back</button>
            <button onClick={handleVerify} disabled={loading || !otp.trim()} className={BTN_PRIMARY}>
              {loading ? "Verifying..." : "Verify"}
            </button>
          </div>
        </>
      )}
      <ErrorBox msg={error} />
    </div>
  );
}

// ── Method 2: Session String ───────────────────────────────────────────────────

function SessionForm({ projectId, onSuccess }) {
  const [sessionStr, setSessionStr] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleImport() {
    setError("");
    setLoading(true);
    try {
      await api.addSessionAccount(sessionStr.trim(), projectId);
      setSessionStr("");
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-400">
        Paste a Telethon <code className="text-indigo-300 bg-slate-900 px-1 py-0.5 rounded">StringSession</code> to import the account directly.
      </p>
      <textarea
        value={sessionStr}
        onChange={(e) => setSessionStr(e.target.value)}
        placeholder="1BVtsOHoBu..."
        rows={4}
        className={INPUT + " font-mono text-xs resize-none"}
      />
      <button
        onClick={handleImport}
        disabled={loading || !sessionStr.trim()}
        className={BTN_PRIMARY}
      >
        {loading ? "Validating..." : "Import Account"}
      </button>
      <ErrorBox msg={error} />
    </div>
  );
}

// ── Method 3: TData Folder ─────────────────────────────────────────────────────

function TDataForm({ projectId, onSuccess }) {
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  function handleFiles(fileList) {
    setFiles(Array.from(fileList));
    setError("");
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    const items = e.dataTransfer.files;
    if (items.length) handleFiles(items);
  }

  async function handleImport() {
    if (!files.length) return;
    setError("");
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("project_id", projectId);
      for (const file of files) {
        formData.append("files", file);
        formData.append("paths", file.webkitRelativePath || file.name);
      }
      const res = await fetch("/accounts/add/tdata", { method: "POST", body: formData });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Import failed");
      }
      setFiles([]);
      onSuccess();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const folderName = files.length ? files[0].webkitRelativePath?.split("/")[0] || "Selected" : null;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-slate-400">
        Select your Telegram <code className="text-indigo-300 bg-slate-900 px-1 py-0.5 rounded">tdata</code> folder.
        Files are deleted from the server immediately after conversion.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-indigo-500 bg-indigo-500/10"
            : files.length
            ? "border-green-500/50 bg-green-500/5"
            : "border-slate-600 hover:border-slate-400"
        }`}
      >
        {files.length ? (
          <div>
            <p className="text-sm font-medium text-green-400">📁 {folderName}</p>
            <p className="text-xs text-slate-400 mt-1">{files.length} files selected</p>
          </div>
        ) : (
          <div>
            <p className="text-2xl mb-2">📂</p>
            <p className="text-sm text-slate-300">Drag & drop tdata folder</p>
            <p className="text-xs text-slate-500 mt-1">or click to browse</p>
          </div>
        )}
      </div>

      {/* Hidden folder input */}
      <input
        ref={inputRef}
        type="file"
        webkitdirectory="true"
        multiple
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      <button
        onClick={handleImport}
        disabled={loading || !files.length}
        className={BTN_PRIMARY}
      >
        {loading ? "Converting & importing..." : "Import TData"}
      </button>
      <ErrorBox msg={error} />
    </div>
  );
}

// ── Shared UI helpers ──────────────────────────────────────────────────────────

function ErrorBox({ msg }) {
  if (!msg) return null;
  return (
    <p className="text-xs text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{msg}</p>
  );
}

const INPUT =
  "bg-slate-900 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 transition-colors w-full";
const BTN_PRIMARY =
  "w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl py-2.5 text-sm font-medium transition-colors";
const BTN_SECONDARY =
  "flex-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-xl py-2.5 text-sm transition-colors";
