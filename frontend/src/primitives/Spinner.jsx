import styles from "./Spinner.module.css";

export default function Spinner({ size = 16, label, className }) {
  const cls = [styles.spinner, className].filter(Boolean).join(" ");
  const style = { width: size, height: size, borderWidth: Math.max(2, Math.round(size / 8)) };
  return (
    <span className={styles.wrap} role="status" aria-live="polite">
      <span className={cls} style={style} aria-hidden="true" />
      {label && <span className={styles.label}>{label}</span>}
    </span>
  );
}
