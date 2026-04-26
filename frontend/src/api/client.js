const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

class ApiError extends Error {
  constructor(res, text) {
    super(`${res.status} ${res.statusText}: ${text}`);
    this.name = "ApiError";
    this.status = res.status;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res, text);
  }
  return res.json();
}

export const api = {
  createQuery: (userText) =>
    request("/queries", { method: "POST", body: { user_text: userText } }),
  getQuery: (queryId) => request(`/queries/${queryId}`),
  answerQuery: (queryId, followupText) =>
    request(`/queries/${queryId}/answers`, {
      method: "POST",
      body: { followup_text: followupText },
    }),
  getShoppingList: (shoppingListId) =>
    request(`/shopping-lists/${shoppingListId}`),
  startSearch: (shoppingListId) =>
    request(`/shopping-lists/${shoppingListId}/search`, { method: "POST" }),
  getSearchStatus: (shoppingListId) =>
    request(`/shopping-lists/${shoppingListId}/search-status`),
  getCandidates: (shoppingListId) =>
    request(`/shopping-lists/${shoppingListId}/candidates`),
  addToBargain: (shoppingListId, itemId, listingIds) =>
    request(`/shopping-lists/${shoppingListId}/bargain`, {
      method: "POST",
      body: { item_id: itemId, listing_ids: listingIds },
    }),
  getBargainItems: (shoppingListId) =>
    request(`/shopping-lists/${shoppingListId}/bargain-items`),
};
