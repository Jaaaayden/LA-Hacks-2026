import { useCallback, useEffect, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import { ArrowRightIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { followupFor } from "../data/mocks.js";
import { api } from "../api/client.js";
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
    queryText,
    parsedIntent,
    detectedHobby,
    detectedBudget,
    followupQuestions,
    setFollowupQuestions,
    followupAnswers,
    setFollowupAnswers,
  } = useKit();

  // Hydrate questions: real backend if available, mock fallback by hobby.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (followupQuestions?.length) return;
      try {
        const intent = parsedIntent?.parsed_intent || parsedIntent;
        if (intent) {
          const result = await api.followup(intent);
          if (!cancelled && Array.isArray(result?.questions)) {
            setFollowupQuestions(normalizeQuestions(result.questions));
            return;
          }
        }
      } catch (e) {
        console.warn("[followup] backend offline, using mock:", e.message);
      }
      if (!cancelled) {
        setFollowupQuestions(normalizeQuestions(followupFor(detectedHobby)));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [
    detectedHobby,
    parsedIntent,
    followupQuestions?.length,
    setFollowupQuestions,
  ]);

  const kicker = useMemo(
    () =>
      buildKicker({
        hobby: detectedHobby || parsedIntent?.parsed_intent?.hobby,
        budget: detectedBudget ?? parsedIntent?.parsed_intent?.budget_usd,
        queryText,
      }),
    [detectedHobby, detectedBudget, parsedIntent, queryText],
  );

  const setAnswer = useCallback(
    (idx, val) => setFollowupAnswers({ ...followupAnswers, [idx]: val }),
    [followupAnswers, setFollowupAnswers],
  );

  const submit = useCallback(() => {
    navigate(`/kit/${id}`);
  }, [id, navigate]);

  const skip = useCallback(() => {
    setFollowupAnswers({});
    navigate(`/kit/${id}`);
  }, [id, navigate, setFollowupAnswers]);

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
    <StepFrame step={2} label="A few quick questions">
      <div className={styles.layout}>
        {kicker && <div className={styles.kicker}>{kicker}</div>}
        <h1 className={styles.headline}>Before I start hunting…</h1>
        <p className={styles.subhead}>
          A few quick clarifications so I can build the right kit for you.
          Answer in your own words — short or long, both work.
        </p>

        <div className={styles.questions}>
          {(followupQuestions || []).map((q, idx) => (
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
            Skip — go straight to the kit
          </button>
          <div className={styles.actionsRight}>
            <span className={styles.shortcut}>
              <kbd>⌘↵</kbd> when done
            </span>
            <Button onClick={submit} iconEnd={<ArrowRightIcon />}>
              Build my kit
            </Button>
          </div>
        </div>
      </div>
    </StepFrame>
  );
}
