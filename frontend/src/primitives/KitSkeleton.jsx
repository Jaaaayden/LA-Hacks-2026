import styles from "./KitSkeleton.module.css";

export default function KitSkeleton({ rows = 5 }) {
  return (
    <div className={styles.layout} aria-busy="true" aria-live="polite">
      <div>
        <div className={`${styles.bar} ${styles.kicker}`} />
        <div className={`${styles.bar} ${styles.headline}`} />
        <div className={`${styles.bar} ${styles.subhead}`} />
        <div className={`${styles.bar} ${styles.section}`} />
        <div className={styles.itemList}>
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className={styles.item} style={{ animationDelay: `${i * 60}ms` }}>
              <div className={`${styles.bar} ${styles.thumb}`} />
              <div className={styles.itemMain}>
                <div className={`${styles.bar} ${styles.itemTitle}`} />
                <div className={styles.chips}>
                  <div className={`${styles.bar} ${styles.chip}`} />
                  <div className={`${styles.bar} ${styles.chip}`} style={{ width: 110 }} />
                </div>
              </div>
              <div className={`${styles.bar} ${styles.price}`} />
            </div>
          ))}
        </div>
      </div>
      <aside>
        <div className={styles.sidebar}>
          <div className={`${styles.bar} ${styles.kicker}`} />
          <div className={`${styles.bar} ${styles.total}`} />
          <div className={`${styles.bar} ${styles.subhead}`} />
          <div className={`${styles.bar} ${styles.button}`} />
        </div>
      </aside>
    </div>
  );
}
