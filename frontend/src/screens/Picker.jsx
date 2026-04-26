import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import { ArrowRightIcon, CheckIcon, StarIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import styles from "./Picker.module.css";

const CONDITION_LABEL = {
  new: "New",
  like_new: "Like new",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
};

function condDotClass(condition) {
  if (condition === "like_new") return styles.condDotLikeNew;
  if (condition === "fair" || condition === "poor") return styles.condDotFair;
  return ""; // default green for "good" / "new"
}

export default function Picker() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { kit, picks, setPicks } = useKit();

  // Active slots = checked items only, in their declared order.
  const slots = useMemo(
    () => (kit?.items || []).filter((it) => it.checked).map((it) => it.slot),
    [kit?.items],
  );

  const [slotIndex, setSlotIndex] = useState(0);
  const currentSlot = slots[slotIndex];
  const item = kit?.items.find((it) => it.slot === currentSlot);
  const candidates = [];

  const selectedIds = picks[currentSlot] || [];

  function toggle(listingId) {
    const next = selectedIds.includes(listingId)
      ? selectedIds.filter((x) => x !== listingId)
      : [...selectedIds, listingId];
    setPicks({ ...picks, [currentSlot]: next });
  }

  function advance() {
    if (slotIndex + 1 < slots.length) {
      setSlotIndex(slotIndex + 1);
    } else {
      navigate(`/active/${id}`);
    }
  }

  function skipCategory() {
    setPicks({ ...picks, [currentSlot]: [] });
    advance();
  }

  if (!item || candidates.length === 0) {
    const message =
      "Listing search is being rebuilt. You can keep moving through the demo flow for now.";

    return (
      <StepFrame step={4} label="Pick" showBack={false}>
        <div
          style={{
            padding: "60px 40px",
            textAlign: "center",
            color: "var(--ink-muted)",
            display: "flex",
            flexDirection: "column",
            gap: 16,
            alignItems: "center",
          }}
        >
          <p>{message}</p>
          <Button onClick={advance} iconEnd={<ArrowRightIcon />}>
            {slotIndex + 1 < slots.length ? "Skip · next slot" : "Start hunting"}
          </Button>
        </div>
      </StepFrame>
    );
  }

  const itemNoun = item.label.toLowerCase();
  const itemNounPlural = item.slot === "snowboard" ? "boards" : itemNoun;

  return (
    <StepFrame
      step={4}
      label={`Pick · ${slotIndex + 1} of ${slots.length}`}
      showBack={false}
    >
      <div className={styles.layout}>
        <h1 className={styles.headline}>Pick the {itemNounPlural} you like.</h1>
        <p className={styles.subhead}>
          Choose any you'd consider. I'll go bargain on each one and bring you
          the best result.
        </p>

        <div className={styles.controls}>
          <span>{candidates.length} candidates</span>
          <div className={styles.controlsRight}>
            <button className={styles.controlBtn}>Best match ▾</button>
            <button className={styles.controlBtn}>Show 5 more</button>
          </div>
        </div>

        <div className={styles.grid}>
          {candidates.map((c, idx) => {
            const selected = selectedIds.includes(c.listing_id);
            return (
              <div
                key={c.listing_id}
                style={{ animationDelay: `${idx * 60}ms` }}
                className={[
                  styles.card,
                  selected && styles.cardSelected,
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => toggle(c.listing_id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggle(c.listing_id);
                  }
                }}
              >
                {c.is_top_match && (
                  <span className={styles.topMatch}>Top match</span>
                )}
                {selected && (
                  <span className={styles.checkBadge}>
                    <CheckIcon width={13} height={13} />
                  </span>
                )}
                <div className={styles.imgWrap}>
                  <ImageWithFallback
                    src={c.image_url}
                    slot={currentSlot}
                    size={120}
                  />
                </div>
                <div className={styles.body}>
                  <div className={styles.title}>{c.title}</div>
                  <div className={styles.priceRow}>
                    <span className={styles.price}>${c.price_usd}</span>
                    {c.list_price_usd > c.price_usd && (
                      <span className={styles.priceWas}>
                        ${c.list_price_usd}
                      </span>
                    )}
                  </div>
                  <div className={styles.meta}>
                    <span
                      className={[styles.condDot, condDotClass(c.condition)]
                        .filter(Boolean)
                        .join(" ")}
                    />
                    <span>
                      {CONDITION_LABEL[c.condition] || c.condition}
                    </span>
                    <span className={styles.rating}>
                      <span className={styles.starIcon}>
                        <StarIcon width={11} height={11} />
                      </span>
                      {c.rating}
                    </span>
                  </div>
                  <div className={styles.locLine}>{c.location}</div>
                  <div className={styles.blurb}>{c.blurb}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className={styles.footer}>
        <div className={styles.footerLeft}>
          <span className={styles.footerCount}>
            {selectedIds.length} {itemNounPlural} selected
          </span>
          <span className={styles.footerNote}>
            I'll message {selectedIds.length || "no"} sellers in parallel and
            report back with the best result.
          </span>
        </div>
        <div className={styles.footerActions}>
          <button className={styles.controlBtn} onClick={skipCategory}>
            Skip this category
          </button>
          <Button
            onClick={advance}
            disabled={selectedIds.length === 0}
            iconEnd={<ArrowRightIcon />}
          >
            {slotIndex + 1 < slots.length
              ? "Bargain on these"
              : "Start hunting"}
          </Button>
        </div>
      </div>
    </StepFrame>
  );
}
