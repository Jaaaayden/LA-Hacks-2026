import { useState } from "react";
import { getSlotGlyph } from "./icons.jsx";
import styles from "./ImageWithFallback.module.css";

function isUsable(url) {
  return typeof url === "string" && /^https?:\/\//.test(url);
}

export default function ImageWithFallback({
  src,
  slot = "snowboard",
  size = 56,
  alt = "",
  className,
}) {
  const [errored, setErrored] = useState(false);
  const showImage = isUsable(src) && !errored;
  const Glyph = getSlotGlyph(slot);

  return (
    <span
      className={[styles.wrap, className].filter(Boolean).join(" ")}
      style={{ width: size, height: size }}
      aria-hidden={!alt}
    >
      {showImage ? (
        <img
          className={styles.img}
          src={src}
          alt={alt}
          onError={() => setErrored(true)}
        />
      ) : (
        <Glyph />
      )}
    </span>
  );
}
