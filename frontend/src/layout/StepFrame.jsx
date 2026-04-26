import { Link, useLocation, useNavigate } from "react-router-dom";
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
  const location = useLocation();
  return (
    <div className={styles.frame}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Link to="/" className={styles.brand} aria-label="hobbify — home">
            hobbify
          </Link>
          {showBack && (
            <button className={styles.back} onClick={() => navigate(-1)}>
              <ArrowLeftIcon /> Back
            </button>
          )}
        </div>

        <div className={styles.step}>
          {rightSlot ?? (
            <>
              Step {step} of {total} · {label}
            </>
          )}
        </div>
      </header>
      {/* keyed on pathname so the enter animation replays on every navigation */}
      <main key={location.pathname} className={styles.body}>{children}</main>
    </div>
  );
}
