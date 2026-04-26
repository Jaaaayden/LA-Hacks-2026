import { useNavigate } from "react-router-dom";
import { ArrowLeftIcon } from "../primitives/icons.jsx";
import styles from "./StepFrame.module.css";

export default function StepFrame({
  step,
  total = 5,
  label,
  showBack = true,
  rightSlot,
  children,
}) {
  const navigate = useNavigate();
  return (
    <div className={styles.frame}>
      <header className={styles.header}>
        {showBack ? (
          <button className={styles.back} onClick={() => navigate(-1)}>
            <ArrowLeftIcon /> Back
          </button>
        ) : (
          <span />
        )}

        <div className={styles.step}>
          {rightSlot ?? (
            <>
              Step {step} of {total} · {label}
            </>
          )}
        </div>
      </header>
      <main className={styles.body}>{children}</main>
    </div>
  );
}
