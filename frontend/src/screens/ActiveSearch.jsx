import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Stat from "../primitives/Stat.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import { ArrowRightIcon } from "../primitives/icons.jsx";
import { MOCK_ACTIVE } from "../data/mocks.js";
import styles from "./ActiveSearch.module.css";

const STATUS_LABEL = {
  negotiating: "Negotiating",
  messaging: "Messaging",
  just_found: "Just found",
  agreed: "Agreed",
};

// Lightweight scripted "activity" — adds a new line every ~6s to give the
// dashboard a live feel during a demo. Replace with real SSE/polling later.
const SCRIPTED_TICKS = [
  { time_label: "now", text: "Marcus T. agreed to $108 — Burton Custom is ours." },
  {
    time_label: "now",
    text: "Priya S. confirmed Cartel bindings fit Burton baseplate.",
  },
  { time_label: "now", text: "Jake R. opened the boots thread." },
];

export default function ActiveSearch() {
  useParams(); // currently just for URL shape; data is mock
  const [filter, setFilter] = useState("all");
  const [activity, setActivity] = useState(MOCK_ACTIVE.activity);

  // Drip-feed extra activity rows every 6 seconds.
  useEffect(() => {
    let i = 0;
    const id = setInterval(() => {
      if (i >= SCRIPTED_TICKS.length) {
        clearInterval(id);
        return;
      }
      setActivity((prev) => [SCRIPTED_TICKS[i], ...prev]);
      i += 1;
    }, 6000);
    return () => clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    if (filter === "all") return MOCK_ACTIVE.items;
    return MOCK_ACTIVE.items.filter((it) => it.status === filter);
  }, [filter]);

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
            Active search · {MOCK_ACTIVE.items[0]?.label && "Snowboarding"}
          </div>
          <h1 className={styles.headline}>Your kit, in motion.</h1>

          <div className={styles.statRow}>
            <Stat
              label="Committed"
              value={`$${MOCK_ACTIVE.committed_usd}`}
              sub={`of $${MOCK_ACTIVE.budget_usd}`}
              progress={MOCK_ACTIVE.committed_usd / MOCK_ACTIVE.budget_usd}
            />
            <Stat
              label="Negotiating"
              value={MOCK_ACTIVE.negotiating_count}
              sub={`avg counter saving · ${MOCK_ACTIVE.avg_counter_saving_pct}%`}
            />
            <Stat
              label="Agreed"
              value={MOCK_ACTIVE.agreed_count}
              sub={`${MOCK_ACTIVE.pickups_scheduled} pickup scheduled`}
            />
            <Stat
              label="Time saved"
              value={`~${MOCK_ACTIVE.time_saved_hours}h`}
              sub={`${MOCK_ACTIVE.listings_reviewed} listings reviewed`}
            />
          </div>

          <div className={styles.itemsHeader}>
            <span className={styles.itemsHeaderLeft}>
              Items in flight · {MOCK_ACTIVE.items.length}
            </span>
            <div className={styles.filters}>
              {["all", "negotiating", "agreed"].map((f) => (
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
            {filtered.map((it, idx) => (
              <div
                key={it.slot}
                className={styles.itemRow}
                style={{ animationDelay: `${idx * 60}ms` }}
              >
                <div className={styles.imgWithBadge}>
                  <ImageWithFallback slot={it.slot} size={56} />
                  <span className={styles.dateBadge}>{it.added_label}</span>
                </div>
                <div className={styles.itemBody}>
                  <div className={styles.itemHead}>
                    <span>{it.label}</span>
                    <span
                      className={styles.statusChip}
                      data-status={it.status}
                    >
                      {STATUS_LABEL[it.status]}
                    </span>
                  </div>
                  <div className={styles.itemTitle}>{it.title}</div>
                  <div className={styles.itemMeta}>{it.meta}</div>
                </div>
                <div className={styles.priceCol}>
                  <div className={styles.priceRow}>
                    <span className={styles.priceMain}>
                      ${it.target_price}
                    </span>
                    <span className={styles.priceWas}>${it.list_price}</span>
                  </div>
                  <span className={styles.priceLabel}>
                    target · saving ${it.saving}
                  </span>
                </div>
                <div className={styles.priceCol}>
                  <span className={styles.statusText}>{it.status_text}</span>
                  <button className={styles.viewLink}>
                    View <ArrowRightIcon />
                  </button>
                </div>
              </div>
            ))}
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
            {activity.map((a, i) => (
              <div key={i}>
                <div className={styles.activityItem}>
                  <span className={styles.activityTime}>{a.time_label}</span>
                  <span>{a.text}</span>
                </div>
                {i < activity.length - 1 && (
                  <div className={styles.activityRule} style={{ marginTop: 12 }} />
                )}
              </div>
            ))}
          </div>
          <button className={styles.viewLogLink}>View full log →</button>
        </aside>
      </div>
    </StepFrame>
  );
}
