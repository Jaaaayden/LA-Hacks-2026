import styles from "./Stat.module.css";

export default function Stat({ label, value, sub, progress, className }) {
  const cls = [styles.stat, className].filter(Boolean).join(" ");
  return (
    <div className={cls}>
      <div className={styles.label}>{label}</div>
      <div className={styles.value}>{value}</div>
      {progress != null && (
        <div className={styles.bar}>
          <div
            className={styles.barFill}
            style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
          />
        </div>
      )}
      {sub && <div className={styles.sub}>{sub}</div>}
    </div>
  );
}
