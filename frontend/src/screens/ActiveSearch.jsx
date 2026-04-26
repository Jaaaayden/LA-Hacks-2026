import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Stat from "../primitives/Stat.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import { ArrowRightIcon } from "../primitives/icons.jsx";
import { api } from "../api/client.js";
import styles from "./ActiveSearch.module.css";

const POLL_MS = 5000;

function titleize(s) {
  return String(s || "item")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function relativeTime(iso) {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function effectiveTargetPrice(item) {
  const sellerPrice = Number(item?.price_usd || 0);
  const targetPrice = Number(item?.target_price_usd || 0);
  if (sellerPrice > 0 && targetPrice > 0) return Math.min(sellerPrice, targetPrice);
  return targetPrice || sellerPrice || 0;
}

const STATUS_LABEL = {
  queued: "Queued",
  messaging: "Messaging",
  agreed: "Agreed",
  gave_up: "Passed",
  error: "Error",
};

export default function ActiveSearch() {
  const { id } = useParams();
  const [filter, setFilter] = useState("all");
  const [items, setItems] = useState([]);
  const [activity, setActivity] = useState([]);

  // Load bargain items and poll for updates.
  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;

    async function fetchItems() {
      try {
        const data = await api.getBargainItems(id);
        if (cancelled) return;
        setItems(data || []);

        const feed = [];
        for (const item of data || []) {
          const conv = item.conversation || [];
          if (conv.length > 0) {
            feed.push({
              time_label: relativeTime(item.updated_at),
              text: `Sent opening message to seller about ${item.title}.`,
            });
          } else if (item.status === "queued" || item.status === "messaging") {
            feed.push({
              time_label: relativeTime(item.added_at),
              text: `Added ${item.title} to bargain queue.`,
            });
          }
        }
        setActivity(feed.reverse());
      } catch (err) {
        if (!cancelled) console.warn("[active-search] fetch failed:", err.message);
      }
    }

    fetchItems();
    const handle = setInterval(fetchItems, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [id]);

  // Keep the backend negotiator poller running while this screen is open.
  useEffect(() => {
    if (!id) return undefined;
    api.startNegotiationPoller(id).catch((err) => {
      console.warn("[active-search] start poller failed:", err.message);
    });
    return undefined;
  }, [id]);

  const filtered = useMemo(() => {
    if (filter === "all") return items;
    return items.filter((it) => it.status === filter);
  }, [items, filter]);

  const negotiatingCount = items.filter((it) => it.status === "messaging").length;
  const agreedCount = items.filter((it) => it.status === "agreed").length;
  const committedUsd = items
    .filter((it) => it.status === "agreed")
    .reduce((s, it) => s + effectiveTargetPrice(it), 0);

  const headerRight = (
    <span className={styles.headerStatus}>
      <span className={styles.workingDot}>
        <span className={styles.dotBlink} /> Hobbyist working
      </span>
      <button className={styles.viewLogLink} style={{ padding: 0 }}>
        Pause agent
      </button>
      <button className={styles.viewLogLink} style={{ padding: 0 }}>
        Settings
      </button>
    </span>
  );

  return (
    <StepFrame step={5} label="Active search" rightSlot={headerRight} showBack={false}>
      <div className={styles.layout}>
        <div>
          <div className={styles.kicker}>
            Active search
          </div>
          <h1 className={styles.headline}>Your kit, in motion.</h1>

          <div className={styles.statRow}>
            <Stat
              label="Committed"
              value={`$${committedUsd.toFixed(0)}`}
              sub="agreed items"
              progress={0}
            />
            <Stat
              label="Negotiating"
              value={negotiatingCount}
              sub="opening messages sent"
            />
            <Stat
              label="Agreed"
              value={agreedCount}
              sub="deals closed"
            />
            <Stat
              label="In queue"
              value={items.filter((it) => it.status === "queued").length}
              sub="waiting to message"
            />
          </div>

          <div className={styles.itemsHeader}>
            <span className={styles.itemsHeaderLeft}>
              Items in flight - {items.length}
            </span>
            <div className={styles.filters}>
              {["all", "messaging", "agreed"].map((f) => (
                <button
                  key={f}
                  className={styles.filterBtn}
                  data-active={filter === f}
                  onClick={() => setFilter(f)}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className={styles.itemList}>
            {filtered.length === 0 && (
              <div style={{ padding: "32px 0", color: "var(--ink-muted)" }}>
                No items in flight yet.
              </div>
            )}
            {filtered.map((it, idx) => {
              const sellerPrice = Number(it.price_usd || 0);
              const effectiveTarget = effectiveTargetPrice(it);
              const saving = Math.max(0, sellerPrice - effectiveTarget);
              const statusText =
                it.status === "messaging" && it.last_message
                  ? `Sent: "${it.last_message.slice(0, 60)}${it.last_message.length > 60 ? "..." : ""}"`
                  : it.status === "agreed"
                    ? "Deal agreed"
                    : it.status === "gave_up"
                      ? "Seller firm - passed"
                      : it.status === "error"
                        ? `Error: ${it.error || "unknown"}`
                        : "Queued to message";
              return (
                <div
                  key={it._id || it.listing_id}
                  className={styles.itemRow}
                  style={{ animationDelay: `${idx * 60}ms` }}
                >
                  <div className={styles.imgWithBadge}>
                    <ImageWithFallback slot={it.item_type} size={56} />
                    <span className={styles.dateBadge}>
                      {relativeTime(it.added_at)}
                    </span>
                  </div>
                  <div className={styles.itemBody}>
                    <div className={styles.itemHead}>
                      <span>{titleize(it.item_type)}</span>
                      <span
                        className={styles.statusChip}
                        data-status={it.status}
                      >
                        {STATUS_LABEL[it.status] || it.status}
                      </span>
                    </div>
                    <div className={styles.itemTitle}>{it.title}</div>
                    <div className={styles.itemMeta}>{it.location_raw}</div>
                  </div>
                  <div className={styles.priceCol}>
                    <div className={styles.priceRow}>
                      <span className={styles.priceMain}>
                        ${effectiveTarget.toFixed(0)}
                      </span>
                      {sellerPrice > effectiveTarget && (
                        <span className={styles.priceWas}>${sellerPrice.toFixed(0)}</span>
                      )}
                    </div>
                    <span className={styles.priceLabel}>
                      target - saving ${saving.toFixed(0)}
                    </span>
                  </div>
                  <div className={styles.priceCol}>
                    <span className={styles.statusText}>{statusText}</span>
                    <a
                      href={it.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.viewLink}
                    >
                      View <ArrowRightIcon />
                    </a>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <aside className={styles.sidebar}>
          <div>
            <div className={styles.sidebarTitle}>Live activity</div>
            <div className={styles.sidebarSubtitle}>
              What Hobbyist is doing
            </div>
          </div>
          <div className={styles.activityList}>
            {activity.filter(Boolean).map((a, i, arr) => (
              <div key={i}>
                <div className={styles.activityItem}>
                  <span className={styles.activityTime}>{a.time_label}</span>
                  <span>{a.text}</span>
                </div>
                {i < arr.length - 1 && (
                  <div className={styles.activityRule} style={{ marginTop: 12 }} />
                )}
              </div>
            ))}
          </div>
          <button className={styles.viewLogLink}>View full log -&gt;</button>
        </aside>
      </div>
    </StepFrame>
  );
}
