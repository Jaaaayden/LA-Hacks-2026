import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import Spinner from "../primitives/Spinner.jsx";
import BuildingOverlay from "../primitives/BuildingOverlay.jsx";
import { ArrowRightIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { api } from "../api/client.js";
import { saveKit } from "../state/savedKits.js";
import styles from "./Followup.module.css";

// Normalize whatever the backend or mock gives us into {question, rationale, placeholder}.
function normalizeQuestions(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map((q) =>
    typeof q === "string"
      ? { question: q, rationale: null, placeholder: "" }
      : {
          question: q.question || q.text || "",
          rationale: q.rationale || q.subtext || null,
          placeholder: q.placeholder || "",
        },
  );
}

// Build the kicker line from whatever intent fields we have.
function buildKicker({ hobby, budget, queryText }) {
  const bits = [];
  if (hobby) bits.push(String(hobby).toUpperCase());
  if (budget != null) bits.push(`$${budget}`);
  // Pull a couple of inline numeric specifics from the brief if present.
  const sizeMatch = queryText?.match(/\b(?:size\s)?(\d{1,2})(?=\s?(?:boot|inch|in)\b)/i);
  if (sizeMatch) bits.push(`SIZE ${sizeMatch[1]}`);
  const heightMatch = queryText?.match(/\b\d['′]\s?\d{1,2}["″]?/);
  if (heightMatch) bits.push(heightMatch[0]);
  return bits.join(" · ");
}

export default function Followup() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    setShoppingListId,
    queryText,
    parsedIntent,
    setParsedIntent,
    detectedHobby,
    setDetectedHobby,
    detectedBudget,
    setDetectedBudget,
    followupQuestions,
    setFollowupQuestions,
    followupAnswers,
    setFollowupAnswers,
    setKit,
  } = useKit();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const displayQuestions = useMemo(
    () => normalizeQuestions(followupQuestions),
    [followupQuestions],
  );

  const kicker = useMemo(
    () =>
      buildKicker({
        hobby: detectedHobby || parsedIntent?.parsed_intent?.hobby,
        budget: detectedBudget ?? parsedIntent?.parsed_intent?.budget_usd,
        queryText,
      }),
    [detectedHobby, detectedBudget, parsedIntent, queryText],
  );

  const progress = useMemo(() => {
    const asked = parsedIntent?.questions_asked_count;
    const max = parsedIntent?.max_followup_questions;
    const hasCount = Boolean(asked && max);
    return {
      asked: hasCount ? asked : null,
      max: hasCount ? max : null,
      pct: hasCount ? Math.min(1, asked / max) : null,
      message: hasCount
        ? "Almost there — I'll keep asking until the kit is dialed in."
        : "If you don't know an answer, say so and I'll infer the rest.",
    };
  }, [parsedIntent]);

  const setAnswer = useCallback(
    (idx, val) => setFollowupAnswers({ ...followupAnswers, [idx]: val }),
    [followupAnswers, setFollowupAnswers],
  );

  const completeQuery = useCallback(async (answers) => {
    if (busy) return;
    setBusy(true);
    setError(null);

    const answeredText = displayQuestions
      .map((q, idx) => {
        const answer = (answers[idx] || "").trim();
        if (!answer) return null;
        return `Q: ${q.question}\nA: ${answer}`;
      })
      .filter(Boolean)
      .join("\n\n");
    const followupText = answeredText || "No additional follow-up answers provided.";

    try {
      const result = await api.answerQuery(id, followupText);
      setParsedIntent(result);
      if (result.parsed_intent?.hobby) setDetectedHobby(result.parsed_intent.hobby);
      if (result.parsed_intent?.budget_usd != null)
        setDetectedBudget(result.parsed_intent.budget_usd);

      if (result.done === false) {
        setFollowupQuestions(result.followup_questions || []);
        setFollowupAnswers({});
        saveKit({
          id,
          route: `/followup/${id}`,
          queryId: id,
          shoppingListId: null,
          queryText,
          parsedIntent: result,
          detectedHobby: result.parsed_intent?.hobby || detectedHobby || null,
          detectedBudget:
            result.parsed_intent?.budget_usd ?? detectedBudget ?? null,
          hobby: result.parsed_intent?.hobby || detectedHobby || null,
          budget_usd: result.parsed_intent?.budget_usd ?? detectedBudget ?? null,
          followupQuestions: result.followup_questions || [],
          followupAnswers: {},
          kit: null,
          status: result.status,
        });
        return;
      }

      setShoppingListId(result.shopping_list_id);
      setKit({ ...result.shopping_list, kit_id: result.shopping_list_id });
      saveKit({
        id: result.shopping_list_id,
        route: `/kit/${result.shopping_list_id}`,
        queryId: id,
        shoppingListId: result.shopping_list_id,
        queryText,
        parsedIntent: result,
        detectedHobby: result.parsed_intent?.hobby || result.shopping_list?.hobby,
        detectedBudget:
          result.parsed_intent?.budget_usd ?? result.shopping_list?.budget_usd ?? null,
        hobby: result.shopping_list?.hobby,
        budget_usd: result.shopping_list?.budget_usd,
        followupQuestions: [],
        followupAnswers: answers,
        kit: { ...result.shopping_list, kit_id: result.shopping_list_id },
        status: result.status,
      });
      navigate(`/kit/${result.shopping_list_id}`);
    } catch (e) {
      console.warn("[queries] answer failed:", e.message);
      setError("Could not continue this kit. Check that the backend is running.");
    } finally {
      setBusy(false);
    }
  }, [
    busy,
    displayQuestions,
    id,
    navigate,
    setDetectedBudget,
    setDetectedHobby,
    setFollowupAnswers,
    setFollowupQuestions,
    setKit,
    setParsedIntent,
    setShoppingListId,
    queryText,
    detectedHobby,
    detectedBudget,
  ]);

  const submit = useCallback(() => {
    completeQuery(followupAnswers);
  }, [completeQuery, followupAnswers]);

  const skip = useCallback(() => {
    setFollowupAnswers({});
    completeQuery({});
  }, [completeQuery, setFollowupAnswers]);

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
    <StepFrame step={2} label="A few quick questions" showBack={false}>
      <div className={styles.layout}>
        {kicker && <div className={styles.kicker}>{kicker}</div>}
        <h1 className={styles.headline}>Before I start hunting…</h1>
        <p className={styles.subhead}>
          A few quick clarifications so I can build the right kit for you.
          Answer in your own words — short or long, both work.
        </p>
        <div className={styles.progressNote}>
          <div className={styles.progressNoteRow}>
            <span className={styles.progressDot} aria-hidden="true">
              <span className={styles.progressDotPulse} />
            </span>
            <span className={styles.progressNoteText}>{progress.message}</span>
          </div>
          {progress.pct != null && (
            <div className={styles.progressBar} aria-hidden="true">
              <div
                className={styles.progressBarFill}
                style={{ width: `${Math.max(6, progress.pct * 100)}%` }}
              />
            </div>
          )}
        </div>

        <div className={styles.questions}>
          {displayQuestions.map((q, idx) => (
            <div key={idx} className={styles.question}>
              <div className={styles.number}>
                {String(idx + 1).padStart(2, "0")}
              </div>
              <div className={styles.qBody}>
                <div className={styles.qHeadline}>{q.question}</div>
                {q.rationale && (
                  <div className={styles.qRationale}>{q.rationale}</div>
                )}
                <textarea
                  className={styles.textarea}
                  rows={2}
                  placeholder={q.placeholder || "Type your answer…"}
                  value={followupAnswers[idx] || ""}
                  onChange={(e) => setAnswer(idx, e.target.value)}
                  onKeyDown={onKeyDown}
                />
              </div>
            </div>
          ))}
        </div>

        <div className={styles.actions}>
          <button className={styles.skipBtn} onClick={skip}>
            Skip these questions
          </button>
          <div className={styles.actionsRight}>
            <span className={styles.shortcut}>
              <kbd>⌘↵</kbd> when done
            </span>
            <Button
              onClick={submit}
              disabled={busy}
              iconEnd={busy ? <Spinner size={14} /> : <ArrowRightIcon />}
            >
              {busy ? "Building" : "Build my kit"}
            </Button>
          </div>
        </div>
        {error && <div className={styles.qRationale}>{error}</div>}
      </div>
      {busy && <BuildingOverlay hobby={detectedHobby || parsedIntent?.parsed_intent?.hobby} />}
    </StepFrame>
  );
}
