// localStorage-backed history of completed kits, so users can resume past
// searches instead of starting a new conversation each time.

const STORAGE_KEY = "kitscout.saved_kits.v1";
const MAX_ENTRIES = 12;

function readAll() {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(entries) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // quota exceeded or storage disabled — silently no-op
  }
}

export function listSavedKits() {
  return readAll().sort((a, b) => (b.savedAt || 0) - (a.savedAt || 0));
}

export function getSavedKit(id) {
  return readAll().find((k) => k.id === id) || null;
}

export function saveKit(entry) {
  if (!entry?.id) return;
  const existing = readAll().filter((k) => k.id !== entry.id);
  const next = [
    { ...entry, savedAt: Date.now() },
    ...existing,
  ].slice(0, MAX_ENTRIES);
  writeAll(next);
}

export function deleteSavedKit(id) {
  writeAll(readAll().filter((k) => k.id !== id));
}

export function clearSavedKits() {
  writeAll([]);
}
