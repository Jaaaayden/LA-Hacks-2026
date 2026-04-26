import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import { Chip, AddChip } from "../primitives/Chip.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import KitSkeleton from "../primitives/KitSkeleton.jsx";
import { ArrowRightIcon, CheckIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { saveKit } from "../state/savedKits.js";
import { api } from "../api/client.js";
import styles from "./BuildKit.module.css";

function fmtPrice(value) {
  if (value == null) return "TBD";
  return `$${value}`;
}

function sumActiveBudgets(items) {
  return items
    .filter((it) => it.checked)
    .reduce((acc, it) => acc + (Number(it.budget_usd ?? it.price_usd) || 0), 0);
}

function titleize(value) {
  return String(value || "item")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function slotFor(item, index) {
  return String(item.slot || item.item_type || `item-${index}`)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function flattenAttributes(attributes = []) {
  return attributes.flatMap((attr, attrIndex) =>
    (attr.value || []).map((entry, valueIndex) => ({
      key: `${attr.key || attrIndex}-${valueIndex}`,
      value: attr.key ? `${attr.key}: ${entry.value}` : entry.value,
      reason: entry.justification || null,
    })),
  );
}

function isDisplayKit(kit) {
  return kit?.items?.every(
    (item) =>
      item.slot &&
      item.label &&
      item.category &&
      Array.isArray(item.preferences) &&
      typeof item.price_usd === "number" &&
      typeof item.checked === "boolean",
  );
}

function normalizeKit(kit, { fallbackHobby, fallbackBudget, fallbackId }) {
  return {
    ...kit,
    kit_id: kit.kit_id || fallbackId,
    hobby: kit.hobby || fallbackHobby || "this hobby",
    budget_usd: kit.budget_usd ?? fallbackBudget ?? null,
    items: (kit.items || []).map((item, index) => {
      const required = item.required ?? item.checked ?? true;
      return {
        ...item,
        slot: item.slot || slotFor(item, index),
        label: item.label || titleize(item.item_type),
        category: item.category || (required ? "essential" : "nice_to_have"),
        preferences: item.preferences || flattenAttributes(item.attributes),
        budget_usd: Number(item.budget_usd ?? item.price_usd) || 0,
        price_usd: Number(item.price_usd ?? item.budget_usd) || 0,
        checked: item.checked ?? required,
      };
    }),
  };
}

function attributesFromPreferences(preferences = []) {
  const grouped = new Map();

  for (const pref of preferences) {
    const rawValue = String(pref.value || "").trim();
    if (!rawValue) continue;

    const separator = rawValue.indexOf(": ");
    const key = separator > 0 && !pref.custom ? rawValue.slice(0, separator) : "preference";
    const value = separator > 0 && !pref.custom ? rawValue.slice(separator + 2) : rawValue;
    const entries = grouped.get(key) || [];
    entries.push({
      value,
      justification: pref.reason || "Added from kit editor.",
    });
    grouped.set(key, entries);
  }

  return Array.from(grouped, ([key, value]) => ({ key, value }));
}

function toShoppingListUpdate(kit) {
  return {
    hobby: kit.hobby,
    budget_usd: kit.budget_usd,
    items: (kit.items || []).map((item) => ({
      id: item.id,
      item_type: item.item_type || item.slot,
      search_query: item.search_query || item.label || item.item_type || item.slot,
      budget_usd: Number(item.budget_usd ?? item.price_usd) || 0,
      required: Boolean(item.checked),
      attributes: attributesFromPreferences(item.preferences),
      notes: item.notes || null,
    })),
  };
}

export default function BuildKit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const {
    kit,
    setKit,
    setQueryId,
    setShoppingListId,
    detectedHobby,
    detectedBudget,
    queryText,
    queryId,
    shoppingListId,
    parsedIntent,
    followupQuestions,
    followupAnswers,
  } = useKit();
  const customPrefSeq = useRef(0);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [huntBusy, setHuntBusy] = useState(false);
  const [huntError, setHuntError] = useState(null);

  // BuildKit's UI still uses the demo display shape. Normalize the backend
  // shopping-list schema here until the edit/PATCH step gets its own contract.
  useEffect(() => {
    if (!kit) {
      let cancelled = false;
      setLoadError(null);
      api
        .getShoppingList(id)
        .then((shoppingList) => {
          if (cancelled) return;
          setShoppingListId(id);
          if (shoppingList.query_id) setQueryId(shoppingList.query_id);
          setKit({ ...shoppingList, kit_id: id });
        })
        .catch((e) => {
          if (cancelled) return;
          console.warn("[shopping-lists] load failed:", e.message);
          setLoadError("Could not load this kit from the backend.");
        });
      return () => {
        cancelled = true;
      };
    }

    if (!isDisplayKit(kit)) {
      setKit(
        normalizeKit(kit, {
          fallbackHobby: detectedHobby,
          fallbackBudget: detectedBudget,
          fallbackId: id,
        }),
      );
    }
  }, [
    id,
    kit,
    detectedHobby,
    detectedBudget,
    setKit,
    setQueryId,
    setShoppingListId,
  ]);

  const [editingSlot, setEditingSlot] = useState(null);

  const total = useMemo(
    () => (kit ? sumActiveBudgets(kit.items) : 0),
    [kit],
  );

  // Persist to localStorage so the user can resume this kit later instead of
  // re-running the intake flow. Only save once the kit is in display shape.
  useEffect(() => {
    if (!kit || !isDisplayKit(kit)) return;
    const backendQueryId = queryId || kit.query_id;
    const backendShoppingListId = shoppingListId || kit.kit_id;
    if (!backendQueryId && !backendShoppingListId) return;
    saveKit({
      id: kit.kit_id || id,
      route: `/kit/${kit.kit_id || id}`,
      hobby: kit.hobby,
      budget_usd: kit.budget_usd,
      queryText,
      queryId: backendQueryId,
      shoppingListId: backendShoppingListId,
      parsedIntent,
      detectedHobby,
      detectedBudget,
      followupQuestions,
      followupAnswers,
      kit,
    });
  }, [
    kit,
    id,
    queryText,
    queryId,
    shoppingListId,
    parsedIntent,
    detectedHobby,
    detectedBudget,
    followupQuestions,
    followupAnswers,
  ]);

  if (!kit) {
    return (
      <StepFrame step={3} label="Build kit" showBack={false}>
        {loadError ? (
          <div style={{ padding: 40, color: "var(--ink-muted)" }}>{loadError}</div>
        ) : (
          <KitSkeleton />
        )}
      </StepFrame>
    );
  }

  const essentials = kit.items.filter((it) => it.category === "essential");
  const niceToHave = kit.items.filter((it) => it.category === "nice_to_have");
  const activeItems = kit.items.filter((it) => it.checked);

  function patchItem(slot, patch) {
    const nextKit = {
      ...kit,
      items: kit.items.map((it) =>
        it.slot === slot ? { ...it, ...patch } : it,
      ),
    };
    setKit(nextKit);
    setSaveError(null);

    api.updateShoppingList(nextKit.kit_id || id, toShoppingListUpdate(nextKit)).catch((e) => {
      console.warn("[shopping-lists] save failed:", e.message);
      setSaveError("Could not save this kit edit to the backend.");
    });
  }

  function removePref(slot, key) {
    const target = kit.items.find((it) => it.slot === slot);
    if (!target) return;
    patchItem(slot, {
      preferences: target.preferences.filter((p) => p.key !== key),
    });
  }

  function addPref(slot, value) {
    const trimmed = value.trim();
    if (!trimmed) return;
    const target = kit.items.find((it) => it.slot === slot);
    if (!target) return;
    customPrefSeq.current += 1;
    const key = `custom-${customPrefSeq.current}`;
    patchItem(slot, {
      preferences: [
        ...target.preferences,
        { key, value: trimmed, reason: null, custom: true },
      ],
    });
  }

  async function startHunt() {
    if (huntBusy) return;
    const listId = kit.kit_id || id;
    setHuntBusy(true);
    setHuntError(null);

    try {
      await api.startSearch(listId);
      navigate(`/pick/${listId}`);
    } catch (e) {
      console.warn("[shopping-lists] search failed:", e.message);
      setHuntError("Could not start listing search. Check that the backend is running.");
    } finally {
      setHuntBusy(false);
    }
  }

  return (
    <StepFrame step={3} label="Build kit" showBack={false}>
      <div className={styles.layout}>
        {/* LEFT: items */}
        <div>
          <div className={styles.kicker}>
            {kit.hobby?.toUpperCase()} · {fmtPrice(kit.budget_usd)} BUDGET
          </div>
          <h1 className={styles.headline}>Build your kit.</h1>
          <p className={styles.subhead}>
            Uncheck anything you already have — Hobbyist will only hunt for
            what's still on the list.
          </p>
          {saveError && <div style={{ color: "var(--ink-muted)", marginBottom: 16 }}>{saveError}</div>}
          {huntError && <div style={{ color: "var(--ink-muted)", marginBottom: 16 }}>{huntError}</div>}

          <div className={styles.sectionLabel}>Essential</div>
          <div className={styles.itemList}>
            {essentials.map((it, idx) => (
              <ItemRow
                key={it.slot}
                index={idx}
                item={it}
                editing={editingSlot === it.slot}
                onEditOpen={() => setEditingSlot(it.slot)}
                onEditClose={() => setEditingSlot(null)}
                onPatch={(patch) => patchItem(it.slot, patch)}
                onRemovePref={(key) => removePref(it.slot, key)}
                onAddPref={(value) => addPref(it.slot, value)}
              />
            ))}
          </div>

          {niceToHave.length > 0 && (
            <>
              <div className={styles.sectionLabel}>Nice to have</div>
              <div className={styles.itemList}>
                {niceToHave.map((it, idx) => (
                  <ItemRow
                    key={it.slot}
                    index={essentials.length + idx}
                    item={it}
                    editing={editingSlot === it.slot}
                    onEditOpen={() => setEditingSlot(it.slot)}
                    onEditClose={() => setEditingSlot(null)}
                    onPatch={(patch) => patchItem(it.slot, patch)}
                    onRemovePref={(key) => removePref(it.slot, key)}
                    onAddPref={(value) => addPref(it.slot, value)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        {/* RIGHT: summary sidebar */}
        <aside className={styles.sidebar}>
          <div className={styles.sidebarCard}>
            <div>
              <div className={styles.totalLabel}>Allocated budget</div>
              <div className={styles.totalValue}>
                {fmtPrice(total)}{" "}
                <span className={styles.totalSub}>of {fmtPrice(kit.budget_usd)}</span>
              </div>
            </div>
            <div className={styles.totalNote}>
              Item budgets are allocated by Hobbyist from the overall cap.
              Final spend depends on listings and negotiation.
            </div>
            <div>
              <div className={styles.willSearchHeader}>
                <span>Will search for</span>
                <span>{activeItems.length}</span>
              </div>
              <div
                className={styles.willSearchList}
                style={{ marginTop: 12 }}
              >
                {activeItems.map((it) => (
                  <div className={styles.willSearchRow} key={it.slot}>
                    <span className={styles.willSearchLeft}>
                      <ImageWithFallback slot={it.slot} size={20} />
                      {it.label}
                    </span>
                    <span className={styles.willSearchPrice}>
                      {fmtPrice(it.budget_usd ?? it.price_usd)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.actions}>
              <Button
                onClick={startHunt}
                disabled={huntBusy}
                iconEnd={<ArrowRightIcon />}
              >
                {huntBusy ? "Starting search" : "Start hunting"}
              </Button>
              <button className={styles.saveLink}>Save for later</button>
            </div>
          </div>
        </aside>
      </div>
    </StepFrame>
  );
}

function ItemRow({
  index = 0,
  item,
  editing,
  onEditOpen,
  onEditClose,
  onPatch,
  onRemovePref,
  onAddPref,
}) {
  const itemBudget = Number(item.budget_usd ?? item.price_usd) || 0;
  const [draftBudget, setDraftBudget] = useState(itemBudget);
  const [addingPref, setAddingPref] = useState(false);
  const [prefDraft, setPrefDraft] = useState("");
  const prefInputRef = useRef(null);

  useEffect(() => {
    setDraftBudget(itemBudget);
  }, [itemBudget]);

  useEffect(() => {
    if (addingPref) prefInputRef.current?.focus();
  }, [addingPref]);

  function commit() {
    const budget = Math.max(0, Number(draftBudget) || 0);
    onPatch({ budget_usd: budget, price_usd: budget });
    onEditClose();
  }

  function commitPref() {
    onAddPref(prefDraft);
    setPrefDraft("");
    setAddingPref(false);
  }

  function cancelPref() {
    setPrefDraft("");
    setAddingPref(false);
  }

  const cls = [
    styles.item,
    !item.checked && styles.itemUnchecked,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls} style={{ animationDelay: `${index * 50}ms` }}>
      <ImageWithFallback slot={item.slot} size={56} />

      <div className={styles.itemMain}>
        <div className={styles.itemTitle}>{item.label}</div>
        <div className={styles.prefRow}>
          {item.preferences.map((p) => (
            <Chip
              key={p.key}
              label={p.value}
              reason={p.reason}
              onRemove={() => onRemovePref(p.key)}
            />
          ))}
          {addingPref ? (
            <input
              ref={prefInputRef}
              className={styles.prefInput}
              value={prefDraft}
              onChange={(e) => setPrefDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitPref();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancelPref();
                }
              }}
              onBlur={() => (prefDraft.trim() ? commitPref() : cancelPref())}
              placeholder="e.g. waterproof"
              maxLength={32}
            />
          ) : (
            <AddChip onClick={() => setAddingPref(true)} />
          )}
        </div>
      </div>

      <div className={styles.priceCol}>
        <span className={styles.priceVal}>
          {fmtPrice(itemBudget)}
        </span>
        <button
          type="button"
          className={styles.priceEdit}
          onClick={() => (editing ? onEditClose() : onEditOpen())}
        >
          edit
        </button>
        {editing && (
          <div className={styles.editor}>
            <div className={styles.editorLabel}>Item budget</div>
            <div className={styles.editorRow}>
              <input
                className={styles.numberInput}
                type="number"
                value={draftBudget}
                onChange={(e) => setDraftBudget(e.target.value)}
                min={0}
              />
            </div>
            <Button variant="primary" onClick={commit}>
              Save
            </Button>
          </div>
        )}
      </div>

      <button
        type="button"
        className={styles.checkbox}
        data-checked={item.checked}
        onClick={() => onPatch({ checked: !item.checked })}
        aria-label={item.checked ? "Uncheck" : "Check"}
      >
        {item.checked && <CheckIcon width={14} height={14} />}
      </button>
    </div>
  );
}
