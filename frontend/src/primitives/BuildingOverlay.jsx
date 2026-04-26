import { useEffect, useState } from "react";
import styles from "./BuildingOverlay.module.css";

const STEPS = [
  "Reading your answers…",
  "Picking the right gear shape…",
  "Sizing essentials to your build…",
  "Pricing against the used market…",
  "Assembling your kit…",
];

export default function BuildingOverlay({ hobby }) {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % STEPS.length);
    }, 1800);
    return () => clearInterval(id);
  }, []);

  return (
    <div className={styles.scrim} role="status" aria-live="polite">
      <div className={styles.card}>
        <div className={styles.dots} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className={styles.headline}>
          Building your {hobby || "kit"}…
        </div>
        <div className={styles.message} key={step}>
          {STEPS[step]}
        </div>
      </div>
    </div>
  );
}
