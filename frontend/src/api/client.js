const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const api = {
  createQuery: (userText) =>
    request("/queries", { method: "POST", body: { user_text: userText } }),
  answerQuery: (queryId, followupText) =>
    request(`/queries/${queryId}/answers`, {
      method: "POST",
      body: { followup_text: followupText },
    }),
};
