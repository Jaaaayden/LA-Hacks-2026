import styles from "./Card.module.css";

export default function Card({
  variant,
  compact = false,
  className,
  children,
  ...rest
}) {
  const cls = [
    styles.card,
    compact && styles.compact,
    variant === "muted" && styles.muted,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={cls} {...rest}>
      {children}
    </div>
  );
}
