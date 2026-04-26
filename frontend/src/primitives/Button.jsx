import styles from "./Button.module.css";

export default function Button({
  variant = "primary",
  iconEnd,
  iconStart,
  children,
  className,
  ...rest
}) {
  const cls = [styles.btn, styles[variant], className].filter(Boolean).join(" ");
  return (
    <button className={cls} {...rest}>
      {iconStart}
      {children}
      {iconEnd && <span className={styles["icon-end"]}>{iconEnd}</span>}
    </button>
  );
}
