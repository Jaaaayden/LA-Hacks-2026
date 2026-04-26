import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import StepFrame from "../layout/StepFrame.jsx";
import Button from "../primitives/Button.jsx";
import { Chip, AddChip } from "../primitives/Chip.jsx";
import ImageWithFallback from "../primitives/ImageWithFallback.jsx";
import { ArrowRightIcon, CheckIcon } from "../primitives/icons.jsx";
import { useKit } from "../state/KitContext.jsx";
import { buildKitFor } from "../data/mocks.js";
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

export default function BuildKit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { kit, setKit, detectedHobby, detectedBudget } = useKit();
  const customPrefSeq = useRef(0);

  // BuildKit's UI still uses the demo display shape. Normalize the backend
  // shopping-list schema here until the edit/PATCH step gets its own contract.
  useEffect(() => {
    if (!kit) {
      setKit(
        buildKitFor({
          hobby: detectedHobby,
          budgetUsd: detectedBudget,
        }),
      );
    } else if (!isDisplayKit(kit)) {
      setKit(
        normalizeKit(kit, {
          fallbackHobby: detectedHobby,
          fallbackBudget: detectedBudget,
          fallbackId: id,
        }),
      );
    }
  }, [id, kit, detectedHobby, detectedBudget, setKit]);

  const [editingSlot, setEditingSlot] = useState(null);

  const total = useMemo(
    () => (kit ? sumActiveBudgets(kit.items) : 0),
    [kit],
  );

  if (!kit) return null;

  const essentials = kit.items.filter((it) => it.category === "essential");
  const niceToHave = kit.items.filter((it) => it.category === "nice_to_have");
  const activeItems = kit.items.filter((it) => it.checked);

  function patchItem(slot, patch) {
    setKit({
      ...kit,
      items: kit.items.map((it) =>
        it.slot === slot ? { ...it, ...patch } : it,
      ),
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

  function startHunt() {
    navigate(`/pick/${kit.kit_id}`);
  }

  return (
    <StepFrame step={3} label="Build kit">
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

          <div className={styles.sectionLabel}>Essential</div>
          <div className={styles.itemList}>
            {essentials.map((it) => (
              <ItemRow
                key={it.slot}
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
                {niceToHave.map((it) => (
                  <ItemRow
                    key={it.slot}
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
              <Button onClick={startHunt} iconEnd={<ArrowRightIcon />}>
                Start hunting
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
    <div className={cls}>
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
