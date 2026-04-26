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

function fmtRange([lo, hi]) {
  return `$${lo}–$${hi}`;
}

function sumActiveRanges(items) {
  return items
    .filter((it) => it.checked)
    .reduce(
      (acc, it) => [
        acc[0] + it.price_range_usd[0],
        acc[1] + it.price_range_usd[1],
      ],
      [0, 0],
    );
}

export default function BuildKit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { kit, setKit, detectedHobby, detectedBudget } = useKit();

  // Build a hobby-aware kit on first arrival. If we detected a hobby in the
  // brief, use its template; otherwise fall back to the generic kit. Real
  // /kit/build response will replace this once the backend ships.
  useEffect(() => {
    if (!kit) {
      setKit(
        buildKitFor({
          hobby: detectedHobby,
          budgetUsd: detectedBudget,
        }),
      );
    }
  }, [kit, detectedHobby, detectedBudget, setKit]);

  const [editingSlot, setEditingSlot] = useState(null);

  const totalRange = useMemo(
    () => (kit ? sumActiveRanges(kit.items) : [0, 0]),
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
    const key = `custom-${Date.now()}`;
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
            {kit.hobby?.toUpperCase()} · ${kit.budget_usd} BUDGET
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
              <div className={styles.totalLabel}>Estimated total</div>
              <div className={styles.totalValue}>
                {fmtRange(totalRange)}{" "}
                <span className={styles.totalSub}>of ${kit.budget_usd}</span>
              </div>
            </div>
            <div className={styles.totalNote}>
              Range reflects used-market prices Hobbyist sees right now. Final
              number depends on negotiation.
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
                      {fmtRange(it.price_range_usd)}
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
  const [draftLo, setDraftLo] = useState(item.price_range_usd[0]);
  const [draftHi, setDraftHi] = useState(item.price_range_usd[1]);
  const [addingPref, setAddingPref] = useState(false);
  const [prefDraft, setPrefDraft] = useState("");
  const prefInputRef = useRef(null);

  useEffect(() => {
    setDraftLo(item.price_range_usd[0]);
    setDraftHi(item.price_range_usd[1]);
  }, [item.price_range_usd]);

  useEffect(() => {
    if (addingPref) prefInputRef.current?.focus();
  }, [addingPref]);

  function commit() {
    const lo = Math.max(0, Number(draftLo) || 0);
    const hi = Math.max(lo, Number(draftHi) || lo);
    onPatch({ price_range_usd: [lo, hi] });
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
          {fmtRange(item.price_range_usd)}
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
            <div className={styles.editorLabel}>Price range</div>
            <div className={styles.editorRow}>
              <input
                className={styles.numberInput}
                type="number"
                value={draftLo}
                onChange={(e) => setDraftLo(e.target.value)}
                min={0}
              />
              <input
                className={styles.numberInput}
                type="number"
                value={draftHi}
                onChange={(e) => setDraftHi(e.target.value)}
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
