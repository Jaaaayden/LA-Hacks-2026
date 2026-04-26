import { useState } from "react";
import { InfoIcon, XIcon, PlusIcon } from "./icons.jsx";
import styles from "./Chip.module.css";

export function Chip({
  label,
  reason,
  onRemove,
  variant,
  className,
  ...rest
}) {
  const [showTip, setShowTip] = useState(false);
  const cls = [styles.chip, variant && styles[variant], className]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={cls} {...rest}>
      {reason && (
        <span
          className={styles.info}
          onMouseEnter={() => setShowTip(true)}
          onMouseLeave={() => setShowTip(false)}
          onClick={(e) => {
            e.stopPropagation();
            setShowTip((v) => !v);
          }}
          aria-label="Why this preference"
        >
          <InfoIcon />
        </span>
      )}
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          className={styles.remove}
          onClick={onRemove}
          aria-label="Remove preference"
        >
          <XIcon width={12} height={12} viewBox="0 0 16 16" />
        </button>
      )}
      {reason && showTip && <span className={styles.tooltip}>{reason}</span>}
    </span>
  );
}

export function AddChip({ children = "add preference", ...rest }) {
  return (
    <button type="button" className={styles.add} {...rest}>
      <PlusIcon width={11} height={11} />
      {children}
    </button>
  );
}
