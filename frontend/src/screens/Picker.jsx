import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import { ArrowRightIcon, CheckIcon, StarIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { api } from "../api/client.js";
import styles from "./Picker.module.css";

const POLL_MS = 4000;

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

function titleize(value) {
  return String(value || "item")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function slotFor(item, index) {
  return String(item.slot || item.item_type || item.id || `item-${index}`)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function normalizePickerKit(shoppingList, fallbackId) {
  return {
    ...shoppingList,
    kit_id: shoppingList.kit_id || fallbackId,
    items: (shoppingList.items || []).map((item, index) => {
      const required = item.required ?? item.checked ?? true;
      return {
        ...item,
        slot: item.slot || slotFor(item, index),
        label: item.label || titleize(item.item_type),
        checked: item.checked ?? required,
      };
    }),
  };
}

export default function Picker() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { kit, setKit, setQueryId, setShoppingListId, picks, setPicks } = useKit();
  const [slotIndex, setSlotIndex] = useState(0);
  const [candidatesByItem, setCandidatesByItem] = useState({});
  const [searchStatus, setSearchStatus] = useState(null);
  const [kitLoading, setKitLoading] = useState(!kit);
  const [candidatesLoading, setCandidatesLoading] = useState(true);
  const [kitError, setKitError] = useState(null);
  const [candidateError, setCandidateError] = useState(null);

  useEffect(() => {
    if (kit || !id) {
      setKitLoading(false);
      return undefined;
    }
    let cancelled = false;
    setKitLoading(true);
    setKitError(null);

    api
      .getShoppingList(id)
      .then((shoppingList) => {
        if (cancelled) return;
        setShoppingListId(id);
        if (shoppingList.query_id) setQueryId(shoppingList.query_id);
        setKit(normalizePickerKit(shoppingList, id));
        setKitLoading(false);
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn("[picker] load kit failed:", err.message);
          setKitError("Could not load this kit from the backend.");
          setKitLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, kit, setKit, setQueryId, setShoppingListId]);

  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;

    async function fetchCandidates() {
      setCandidatesLoading(true);
      try {
        const [candidateData, statusData] = await Promise.all([
          api.getCandidates(id),
          api.getSearchStatus(id).catch(() => null),
        ]);
        if (cancelled) return;
        setCandidatesByItem(candidateData || {});
        setSearchStatus(statusData);
        setCandidateError(null);
      } catch (err) {
        if (!cancelled) {
          console.warn("[picker] candidates failed:", err.message);
          setCandidateError("Could not load listing candidates from the backend.");
        }
      } finally {
        if (!cancelled) setCandidatesLoading(false);
      }
    }

    fetchCandidates();
    const handle = setInterval(fetchCandidates, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [id]);

  // Active slots = checked items only, in their declared order.
  const activeItems = useMemo(
    () => (kit?.items || []).filter((it) => it.checked ?? it.required),
    [kit?.items],
  );

  const item = activeItems[slotIndex];
  const currentSlot = item?.slot;
  const candidates = item?.id ? candidatesByItem[item.id] || [] : [];
  const selectedIds = picks[currentSlot] || [];
  const progressLabel = searchStatus
    ? `${searchStatus.items_done || 0} of ${searchStatus.items_total || activeItems.length} categories searched`
    : null;
  const searchIsRunning =
    searchStatus?.status === "pending" || searchStatus?.status === "searching";
  const searchIsOnCurrentItem =
    item?.id && searchStatus?.current_item_id === item.id;
  const currentItemName = item?.label || "items";
  const itemNoun = currentItemName.toLowerCase();
  const itemNounPlural = item?.slot === "snowboard" ? "boards" : itemNoun;
  const stepLabel = activeItems.length
    ? `Pick · ${Math.min(slotIndex + 1, activeItems.length)} of ${activeItems.length}`
    : "Pick";
  const emptyTitle = kitError
    || candidateError
    || (kitLoading
      ? "Loading your kit..."
      : !item
        ? "No active items to pick from."
        : searchStatus?.status === "error"
          ? "Search hit an error."
          : searchIsRunning
            ? `Searching for ${itemNounPlural}...`
            : `No ${itemNounPlural} found yet.`);
  const emptyDetail = kitError
    ? "Try going back to the kit builder and opening this search again."
    : candidateError
      ? "The page will keep retrying while you are here."
      : kitLoading
        ? "Getting the categories you chose before showing listings."
        : !item
          ? "Go back to the kit builder and check at least one item."
          : searchStatus?.status === "error"
            ? searchStatus.error || "The backend search job reported an error."
            : searchIsRunning
              ? searchIsOnCurrentItem
                ? "OfferUp results will appear here as soon as this category is saved."
                : `${titleize(searchStatus?.current_item_type || "another category")} is being searched now. This category is still waiting for results.`
              : "You can skip this category and keep reviewing the rest of the kit.";
  const disablePrimary = !item || selectedIds.length === 0;

  function toggle(listingId) {
    const next = selectedIds.includes(listingId)
      ? selectedIds.filter((x) => x !== listingId)
      : [...selectedIds, listingId];
    setPicks({ ...picks, [currentSlot]: next });
  }

  function advance() {
    if (slotIndex + 1 < activeItems.length) {
      setSlotIndex(slotIndex + 1);
    } else {
      navigate(`/active/${id}`);
    }
  }

  async function bargainAndAdvance() {
    if (selectedIds.length > 0 && item?.id) {
      try {
        await api.addToBargain(id, item.id, selectedIds);
      } catch (err) {
        console.warn("[picker] addToBargain failed:", err.message);
      }
    }
    advance();
  }

  function skipCategory() {
    setPicks({ ...picks, [currentSlot]: [] });
    advance();
  }

  return (
    <StepFrame
      step={4}
      label={stepLabel}
      showBack={false}
    >
      <div className={styles.layout}>
        <h1 className={styles.headline}>Pick the {itemNounPlural} you like.</h1>
        <p className={styles.subhead}>
          Choose any you'd consider. I'll go bargain on each one and bring you
          the best result.
        </p>

        <div className={styles.controls}>
          <span>
            {candidates.length} candidates
            {progressLabel ? ` · ${progressLabel}` : ""}
          </span>
          <div className={styles.controlsRight}>
            <button className={styles.controlBtn}>Best match ▾</button>
            <button className={styles.controlBtn}>Show 5 more</button>
          </div>
        </div>

        <div className={styles.grid}>
          {candidates.length === 0 && (
            <div className={styles.emptyState}>
              <div className={styles.emptyEyebrow}>
                {candidatesLoading && searchIsRunning ? "Still checking" : "Picker status"}
              </div>
              <div className={styles.emptyTitle}>{emptyTitle}</div>
              <div className={styles.emptyDetail}>{emptyDetail}</div>
              {progressLabel && (
                <div className={styles.emptyProgress}>{progressLabel}</div>
              )}
            </div>
          )}
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
            onClick={bargainAndAdvance}
            disabled={disablePrimary}
            iconEnd={<ArrowRightIcon />}
          >
            {slotIndex + 1 < activeItems.length
              ? "Bargain on these"
              : "Start hunting"}
          </Button>
        </div>
      </div>
    </StepFrame>
  );
}
