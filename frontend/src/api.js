const BASE = process.env.REACT_APP_API_URL || "";

async function req(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

export const api = {
  // Projects
  listProjects: () => req("GET", "/projects/list"),
  createProject: (name, tone, context, system_prompt = "") =>
    req("POST", `/projects/create?name=${encodeURIComponent(name)}&tone=${tone}&context=${encodeURIComponent(context)}&system_prompt=${encodeURIComponent(system_prompt)}`),
  updateProject: (id, params) => {
    const qs = new URLSearchParams(params).toString();
    return req("PUT", `/projects/${id}?${qs}`);
  },

  // Accounts
  listAccounts: (project_id) => req("GET", `/accounts/list?project_id=${project_id}`),
  addAccount: (phone, project_id) => req("POST", "/accounts/add/otp", { phone, project_id }),
  verifyAccount: (phone, otp_code, password = "") =>
    req("POST", "/accounts/verify/otp", { phone, otp_code, password }),
  addSessionAccount: (session_string, project_id) =>
    req("POST", "/accounts/add/session", { session_string, project_id }),
  removeAccount: (account_id) => req("DELETE", "/accounts/remove", { account_id }),

  // Inbox
  getInbox: (project_id) => req("GET", `/inbox/${project_id}`),
  getChatHistory: (account_id, chat_id) =>
    req("GET", `/chat/${account_id}/${chat_id}`),
  sendMessage: (account_id, chat_id, text) =>
    req("POST", "/messages/send", { account_id, chat_id, text }),

  // Groups
  listGroups: (project_id) => req("GET", `/groups/list?project_id=${project_id}`),
  joinGroup: (account_id, group_link) =>
    req("POST", "/groups/join", { account_id, group_link }),
  leaveGroup: (account_id, group_id) =>
    req("POST", "/groups/leave", { account_id, group_id }),
  getGroupMessages: (account_id, group_id, limit = 50) =>
    req("GET", `/groups/messages?account_id=${account_id}&group_id=${group_id}&limit=${limit}`),
  toggleMonitor: (account_id, chat_id, monitored) =>
    req("POST", "/groups/toggle-monitor", { account_id, chat_id, monitored }),

  // Sync
  syncAccount: (account_id) => req("POST", `/accounts/sync/${account_id}`),

  // Away mode
  awayStatus: (project_id) => req("GET", `/away/status?project_id=${project_id}`),
  awayEnable: (project_id, hours, target_mode = "all", target_chat_ids = []) =>
    req("POST", "/away/enable", { project_id, hours, target_mode, target_chat_ids }),
  awayDisable: (project_id) => req("POST", `/away/disable?project_id=${project_id}`),
  awayLog: (project_id, unreviewed_only = false) =>
    req("GET", `/away/log?project_id=${project_id}&unreviewed_only=${unreviewed_only}`),
  awayMarkReviewed: (log_id) => req("POST", `/away/log/${log_id}/review`),
  awayMarkAllReviewed: (project_id) => req("POST", `/away/log/review-all?project_id=${project_id}`),

  // AI
  getDraft: (payload) => req("POST", "/ai/draft", payload),

  // Persona
  getPersona: (account_id) => req("GET", `/accounts/${account_id}/persona`),
  updatePersona: (account_id, personality, job_description) =>
    req("PUT", `/accounts/${account_id}/persona`, { personality, job_description }),
  reassignAccountProject: (account_id, project_id) =>
    req("PUT", `/accounts/${account_id}/project?project_id=${project_id}`),

  // Group Discovery
  getSuggestedGroups: (category = "all", project_id = 0) =>
    req("GET", `/discovery/suggested?category=${category}&limit=100&project_id=${project_id}`),
  joinSuggestedGroup: (account_id, group_id) =>
    req("POST", "/discovery/join", { account_id, group_id }),
  runDiscoveryNow: (account_id) =>
    req("POST", `/discovery/run-now?account_id=${account_id}`),
};

export function createWebSocket(project_id, onMessage) {
  const apiUrl = process.env.REACT_APP_API_URL || "";
  const wsBase = apiUrl
    ? apiUrl.replace(/^http/, "ws")
    : `ws://${window.location.hostname}:${window.location.port}`;
  const ws = new WebSocket(`${wsBase}/ws/${project_id}`);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch (_) {}
  };
  ws.onerror = (e) => console.error("WS error", e);
  return ws;
}
