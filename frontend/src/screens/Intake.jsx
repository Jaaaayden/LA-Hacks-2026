import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import Spinner from "../primitives/Spinner.jsx";
import { ArrowRightIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { api } from "../api/client.js";
import { canonicalHobby } from "../data/mocks.js";
import { listSavedKits, deleteSavedKit, saveKit } from "../state/savedKits.js";
import styles from "./Intake.module.css";

const HOBBY_WORDS = [
  "snowboarding",
  "snowboard",
  "skating",
  "skateboard",
  "skateboarding",
  "photography",
  "pottery",
  "bouldering",
  "climbing",
  "guitar",
  "biking",
  "mountain biking",
  "running",
  "yoga",
];

// Patterns we highlight inline (order matters: longer first).
const PATTERNS = [
  { name: "money", re: /\$\s?\d{1,6}(?:[.,]\d{1,2})?/g },
  { name: "height", re: /\b\d['′]\s?\d{1,2}["″]?/g },
  { name: "size", re: /\b(?:size\s)?\d{1,2}(?=\s?(?:boot|inch|in)\b)/gi },
  {
    name: "hobby",
    re: new RegExp(`\\b(${HOBBY_WORDS.join("|")})\\b`, "gi"),
  },
];

function highlightHTML(plain) {
  if (!plain) return "";
  // Find all matches across all patterns, then merge non-overlapping.
  const matches = [];
  for (const { re } of PATTERNS) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(plain))) {
      matches.push({ start: m.index, end: m.index + m[0].length });
    }
  }
  matches.sort((a, b) => a.start - b.start);
  const merged = [];
  for (const x of matches) {
    const last = merged[merged.length - 1];
    if (last && x.start < last.end) {
      last.end = Math.max(last.end, x.end);
    } else {
      merged.push({ ...x });
    }
  }
  let out = "";
  let cursor = 0;
  for (const m of merged) {
    out += escapeHtml(plain.slice(cursor, m.start));
    out += `<span class="${styles.entity}">${escapeHtml(plain.slice(m.start, m.end))}</span>`;
    cursor = m.end;
  }
  out += escapeHtml(plain.slice(cursor));
  return out;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Save/restore caret position across re-renders of the contenteditable.
function getCaretOffset(el) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  const pre = range.cloneRange();
  pre.selectNodeContents(el);
  pre.setEnd(range.endContainer, range.endOffset);
  return pre.toString().length;
}

function setCaretOffset(el, offset) {
  if (offset == null) return;
  const range = document.createRange();
  const sel = window.getSelection();
  let pos = 0;
  let placed = false;

  function walk(node) {
    if (placed) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const next = pos + node.nodeValue.length;
      if (offset <= next) {
        range.setStart(node, offset - pos);
        range.collapse(true);
        placed = true;
      } else {
        pos = next;
      }
    } else {
      for (const child of node.childNodes) walk(child);
    }
  }
  walk(el);
  if (!placed) {
    range.selectNodeContents(el);
    range.collapse(false);
  }
  sel.removeAllRanges();
  sel.addRange(range);
}

function parseClientSide(text) {
  const hobby = canonicalHobby(text);
  const moneyMatch = text.match(/\$\s?(\d{1,6})(?:[.,]\d{1,2})?/);
  const budget_usd = moneyMatch ? Number(moneyMatch[1]) : null;
  return { hobby, budget_usd };
}

export default function Intake() {
  const navigate = useNavigate();
  const {
    setQueryId,
    setShoppingListId,
    setQueryText,
    setParsedIntent,
    setDetectedHobby,
    setDetectedBudget,
    setFollowupQuestions,
    setFollowupAnswers,
    setKit,
    setPicks,
  } = useKit();
  const editorRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [savedKits, setSavedKits] = useState(() => listSavedKits());
  const [resumingId, setResumingId] = useState(null);

  const resume = useCallback(
    async (entry) => {
      if (resumingId) return;
      setResumingId(entry.id);
      setError(null);

      const applyEntry = (nextEntry, route) => {
        setQueryText(nextEntry.queryText || "");
        setQueryId(nextEntry.queryId || null);
        setShoppingListId(nextEntry.shoppingListId || null);
        setParsedIntent(nextEntry.parsedIntent || null);
        setDetectedHobby(nextEntry.detectedHobby || nextEntry.hobby || null);
        setDetectedBudget(nextEntry.detectedBudget ?? nextEntry.budget_usd ?? null);
        setFollowupQuestions(nextEntry.followupQuestions || []);
        setFollowupAnswers(nextEntry.followupAnswers || {});
        setKit(nextEntry.kit || null);
        setPicks({});
        navigate(route || nextEntry.route || `/kit/${nextEntry.id}`);
      };

      try {
        if (entry.queryId) {
          const query = await api.getQuery(entry.queryId);
          const shoppingListId = query.shopping_list_id || entry.shoppingListId;
          if (shoppingListId) {
            const shoppingList = await api.getShoppingList(shoppingListId);
            const freshEntry = {
              ...entry,
              id: shoppingListId,
              route: `/kit/${shoppingListId}`,
              queryId: entry.queryId,
              shoppingListId,
              queryText: query.raw_messages?.[0] || entry.queryText || "",
              parsedIntent: {
                query_id: entry.queryId,
                parsed_intent: query.parsed_intent,
                followup_questions: query.followup_questions || [],
                status: query.status,
                questions_asked_count: query.questions_asked_count,
                max_followup_questions: query.max_followup_questions,
                done: true,
              },
              detectedHobby: query.parsed_intent?.hobby || shoppingList.hobby,
              detectedBudget:
                query.parsed_intent?.budget_usd ?? shoppingList.budget_usd ?? null,
              hobby: shoppingList.hobby,
              budget_usd: shoppingList.budget_usd,
              followupQuestions: [],
              followupAnswers: entry.followupAnswers || {},
              kit: { ...shoppingList, kit_id: shoppingListId },
              status: query.status,
            };
            saveKit(freshEntry);
            setSavedKits(listSavedKits());
            applyEntry(freshEntry, freshEntry.route);
            return;
          }

          const freshEntry = {
            ...entry,
            id: entry.queryId,
            route: `/followup/${entry.queryId}`,
            queryText: query.raw_messages?.[0] || entry.queryText || "",
            parsedIntent: {
              query_id: entry.queryId,
              parsed_intent: query.parsed_intent,
              followup_questions: query.followup_questions || [],
              status: query.status,
              questions_asked_count: query.questions_asked_count,
              max_followup_questions: query.max_followup_questions,
              done: false,
            },
            detectedHobby: query.parsed_intent?.hobby || entry.detectedHobby || null,
            detectedBudget:
              query.parsed_intent?.budget_usd ?? entry.detectedBudget ?? null,
            followupQuestions: query.followup_questions || [],
            followupAnswers: entry.followupAnswers || {},
            kit: null,
            status: query.status,
          };
          saveKit(freshEntry);
          setSavedKits(listSavedKits());
          applyEntry(freshEntry, freshEntry.route);
          return;
        }

        if (entry.shoppingListId || entry.id) {
          const shoppingListId = entry.shoppingListId || entry.id;
          const shoppingList = await api.getShoppingList(shoppingListId);
          const freshEntry = {
            ...entry,
            id: shoppingListId,
            route: `/kit/${shoppingListId}`,
            queryId: shoppingList.query_id || entry.queryId || null,
            shoppingListId,
            detectedHobby: shoppingList.hobby,
            detectedBudget: shoppingList.budget_usd ?? null,
            hobby: shoppingList.hobby,
            budget_usd: shoppingList.budget_usd,
            kit: { ...shoppingList, kit_id: shoppingListId },
          };
          saveKit(freshEntry);
          setSavedKits(listSavedKits());
          applyEntry(freshEntry, freshEntry.route);
          return;
        }

        applyEntry(entry, entry.route);
      } catch (e) {
        console.warn("[queries] resume failed:", e.message);
        if (entry.kit || entry.followupQuestions?.length) {
          applyEntry(entry, entry.route);
        } else {
          setError("Could not resume this search. Check that the backend is running.");
        }
      } finally {
        setResumingId(null);
      }
    },
    [
      navigate,
      resumingId,
      setDetectedBudget,
      setDetectedHobby,
      setFollowupAnswers,
      setFollowupQuestions,
      setKit,
      setParsedIntent,
      setPicks,
      setQueryId,
      setQueryText,
      setShoppingListId,
    ],
  );

  const removeSaved = useCallback((id) => {
    deleteSavedKit(id);
    setSavedKits(listSavedKits());
  }, []);

  const onInput = useCallback(() => {
    const el = editorRef.current;
    if (!el) return;
    const text = el.innerText;
    const caret = getCaretOffset(el);
    el.innerHTML = highlightHTML(text);
    setCaretOffset(el, caret);
  }, []);

  const submit = useCallback(async () => {
    const el = editorRef.current;
    if (!el) return;
    const text = el.innerText.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setQueryText(text);

    // Always run a client-side parse so the kit reacts to the brief even
    // when the backend's offline. Backend response (when available) wins.
    const local = parseClientSide(text);
    setDetectedHobby(local.hobby);
    setDetectedBudget(local.budget_usd);
    // Force fresh kit on each submit so a new query rebuilds the kit.
    setQueryId(null);
    setShoppingListId(null);
    setFollowupQuestions([]);
    setFollowupAnswers({});
    setKit(null);
    setPicks({});

    try {
      const result = await api.createQuery(text);
      const entry = {
        id: result.query_id,
        route: `/followup/${result.query_id}`,
        queryId: result.query_id,
        shoppingListId: null,
        queryText: text,
        parsedIntent: result,
        detectedHobby: result.parsed_intent?.hobby || local.hobby,
        detectedBudget: result.parsed_intent?.budget_usd ?? local.budget_usd,
        hobby: result.parsed_intent?.hobby || local.hobby,
        budget_usd: result.parsed_intent?.budget_usd ?? local.budget_usd,
        followupQuestions: result.followup_questions || [],
        followupAnswers: {},
        kit: null,
        status: result.status,
      };
      setQueryId(result.query_id);
      setParsedIntent(result);
      setFollowupQuestions(result.followup_questions || []);
      if (result.parsed_intent?.hobby) setDetectedHobby(result.parsed_intent.hobby);
      if (result.parsed_intent?.budget_usd != null)
        setDetectedBudget(result.parsed_intent.budget_usd);
      saveKit(entry);
      setSavedKits(listSavedKits());
      navigate(`/followup/${result.query_id}`);
    } catch (e) {
      console.warn("[queries] create failed:", e.message);
      setError("Could not start this search. Check that the backend is running.");
    } finally {
      setBusy(false);
    }
  }, [
    busy,
    navigate,
    setFollowupAnswers,
    setFollowupQuestions,
    setKit,
    setPicks,
    setDetectedBudget,
    setDetectedHobby,
    setParsedIntent,
    setQueryId,
    setQueryText,
    setShoppingListId,
  ]);

  const onKeyDown = useCallback(
    (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    },
    [submit],
  );

  return (
    <StepFrame step={1} label="New search" showBack={false}>
      <div className={styles.center}>
        <div className={styles.inner}>
          <h1 className={styles.headline}>What are you getting into?</h1>

          <div
            ref={editorRef}
            className={styles.input}
            contentEditable="true"
            suppressContentEditableWarning
            onInput={onInput}
            onKeyDown={onKeyDown}
            data-placeholder="I'm getting into snowboarding, budget $300, beginner, size 10 boot, 5'10&quot;."
          />

          <div className={styles.actions}>
            <span className={styles.shortcut}>
              <kbd>⌘↵</kbd> to send
            </span>
            <Button
              onClick={submit}
              disabled={busy}
              iconEnd={busy ? <Spinner size={14} /> : <ArrowRightIcon />}
            >
              {busy ? "Reading your brief" : "Send"}
            </Button>
          </div>

          {error && <div className={styles.error}>{error}</div>}

          {savedKits.length > 0 && (
            <section className={styles.saved}>
              <div className={styles.savedHeader}>
                <span className={styles.savedLabel}>Pick up where you left off</span>
                <span className={styles.savedCount}>{savedKits.length} saved</span>
              </div>
              <div className={styles.savedList}>
                {savedKits.map((entry, idx) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={styles.savedItem}
                    style={{ animationDelay: `${idx * 50}ms` }}
                    onClick={() => resume(entry)}
                    disabled={Boolean(resumingId)}
                  >
                    <div className={styles.savedItemMain}>
                      <div className={styles.savedItemTitle}>
                        {String(entry.hobby || "kit").replace(/^./, (c) => c.toUpperCase())}
                        {entry.budget_usd != null && (
                          <span className={styles.savedItemBudget}> · ${entry.budget_usd}</span>
                        )}
                      </div>
                      {entry.queryText && (
                        <div className={styles.savedItemQuery}>{entry.queryText}</div>
                      )}
                    </div>
                    <div className={styles.savedItemRight}>
                      <span className={styles.savedItemDate}>{relativeTime(entry.savedAt)}</span>
                      {resumingId === entry.id && (
                        <span className={styles.savedItemDate}>opening...</span>
                      )}
                      <span
                        className={styles.savedItemRemove}
                        role="button"
                        tabIndex={0}
                        onClick={(e) => {
                          e.stopPropagation();
                          removeSaved(entry.id);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            e.stopPropagation();
                            removeSaved(entry.id);
                          }
                        }}
                        aria-label="Remove saved search"
                      >
                        ×
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </StepFrame>
  );
}

function relativeTime(ts) {
  if (!ts) return "";
  const diff = Date.now() - ts;
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  if (d < 7) return `${d}d ago`;
  const w = Math.round(d / 7);
  return `${w}w ago`;
}
