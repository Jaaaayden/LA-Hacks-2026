import { createContext, useContext, useMemo, useState } from "react";

const KitContext = createContext(null);

export function KitProvider({ children }) {
  const [queryId, setQueryId] = useState(null);
  const [shoppingListId, setShoppingListId] = useState(null);
  const [parsedIntent, setParsedIntent] = useState(null);
  const [queryText, setQueryText] = useState("");
  const [detectedHobby, setDetectedHobby] = useState(null);
  const [detectedBudget, setDetectedBudget] = useState(null);
  const [followupQuestions, setFollowupQuestions] = useState([]);
  const [followupAnswers, setFollowupAnswers] = useState({});
  const [kit, setKit] = useState(null);
  const [picks, setPicks] = useState({});

  const value = useMemo(
    () => ({
      queryId,
      setQueryId,
      shoppingListId,
      setShoppingListId,
      parsedIntent,
      setParsedIntent,
      queryText,
      setQueryText,
      detectedHobby,
      setDetectedHobby,
      detectedBudget,
      setDetectedBudget,
      followupQuestions,
      setFollowupQuestions,
      followupAnswers,
      setFollowupAnswers,
      kit,
      setKit,
      picks,
      setPicks,
    }),
    [
      queryId,
      shoppingListId,
      parsedIntent,
      queryText,
      detectedHobby,
      detectedBudget,
      followupQuestions,
      followupAnswers,
      kit,
      picks,
    ],
  );

  return <KitContext.Provider value={value}>{children}</KitContext.Provider>;
}

export function useKit() {
  const ctx = useContext(KitContext);
  if (!ctx) throw new Error("useKit must be used inside <KitProvider>");
  return ctx;
}
