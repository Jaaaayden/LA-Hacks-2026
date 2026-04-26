import { createContext, useContext, useMemo, useState } from "react";

const KitContext = createContext(null);

export function KitProvider({ children }) {
  const [parsedIntent, setParsedIntent] = useState(null);
  const [queryText, setQueryText] = useState("");
  const [detectedHobby, setDetectedHobby] = useState(null);
  const [detectedBudget, setDetectedBudget] = useState(null);
  const [kit, setKit] = useState(null);
  const [picks, setPicks] = useState({});

  const value = useMemo(
    () => ({
      parsedIntent,
      setParsedIntent,
      queryText,
      setQueryText,
      detectedHobby,
      setDetectedHobby,
      detectedBudget,
      setDetectedBudget,
      kit,
      setKit,
      picks,
      setPicks,
    }),
    [parsedIntent, queryText, detectedHobby, detectedBudget, kit, picks],
  );

  return <KitContext.Provider value={value}>{children}</KitContext.Provider>;
}

export function useKit() {
  const ctx = useContext(KitContext);
  if (!ctx) throw new Error("useKit must be used inside <KitProvider>");
  return ctx;
}
