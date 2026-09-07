import { MultiFileDiff } from "@pierre/diffs/react";
import { announcementsPayloadSchema } from "@posthog/shared/announcements";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";
import { capture, captureException } from "./analytics";
import { type FlagRecord, readPayload, savePayload } from "./api";
import { POSTHOG_HOST, PROJECT_ID } from "./config";
import {
  blankItem,
  type EditableItem,
  isoToLocalInput,
  localInputToIso,
  newItemId,
  toEditable,
  toPayloadItem,
} from "./items";
import { Stage } from "./Stage";

const DIFF_OPTIONS = {
  theme: { dark: "github-dark", light: "github-light" },
  themeType: "light",
  diffStyle: "split",
  overflow: "wrap",
  disableFileHeader: true,
  tokenizeMaxLineLength: 1000,
} as const;

function rolloutLabel(flag: FlagRecord): { text: string; live: boolean } {
  if (!flag.active) return { text: "flag disabled", live: false };
  const groups = flag.filters.groups as
    | { rollout_percentage?: number | null }[]
    | undefined;
  const percent = Math.max(
    0,
    ...(groups ?? []).map((g) => g.rollout_percentage ?? 100),
  );
  return percent > 0
    ? { text: `${percent}% on air`, live: true }
    : { text: "0% · dark", live: false };
}

function factsFor(item: EditableItem): string {
  if (item.kind === "required-update") {
    return `Blocks every app below ${item.minVersion || "the required version"} until it updates — up-to-date users never see it.`;
  }
  const parts: string[] = [];
  parts.push(
    item.requiresAck
      ? "Blocks until acknowledged; updating counts as acknowledging."
      : "Dismissible — dismissal sticks per user, keyed on the id.",
  );
  if (item.minVersion) {
    parts.push(
      `Apps below ${item.minVersion} get "Update now" instead of the button.`,
    );
  }
  if (item.startsAt || item.endsAt) {
    parts.push("Only shows inside the scheduled window.");
  }
  return parts.join(" ");
}

const FIELD_LABELS: Record<string, string> = {
  title: "title",
  body: "body",
  style: "style",
  hero: "hero",
  cta: "button",
  requiresAck: "blocking",
  ackLabel: "ack label",
  minVersion: "min version",
  startsAt: "schedule",
  endsAt: "schedule",
};

function itemLabel(item: EditableItem): string {
  return item.title || item.id || "untitled";
}

function surfaceLabel(item: EditableItem): string {
  if (item.kind === "required-update") return "required update";
  return item.requiresAck ? "blocking modal" : item.style;
}

/** Plain-English bullets for the publish confirmation, keyed on item ids. */
function describeChanges(
  before: EditableItem[],
  after: EditableItem[],
): string[] {
  const beforeById = new Map(
    before.filter((item) => item.id).map((item) => [item.id, item]),
  );
  const afterIds = new Set(
    after.map((item) => item.id).filter((id) => id !== ""),
  );
  const lines: string[] = [];
  for (const item of after) {
    if (!item.id || !beforeById.has(item.id)) {
      lines.push(`Added "${itemLabel(item)}" (${surfaceLabel(item)})`);
    }
  }
  for (const item of before) {
    if (!afterIds.has(item.id)) lines.push(`Removed "${itemLabel(item)}"`);
  }
  for (const item of after) {
    const prev = item.id ? beforeById.get(item.id) : undefined;
    if (!prev) continue;
    const a = toPayloadItem(prev);
    const b = toPayloadItem(item);
    const changed = [...new Set([...Object.keys(a), ...Object.keys(b)])]
      .filter((key) => JSON.stringify(a[key]) !== JSON.stringify(b[key]))
      .map((key) => FIELD_LABELS[key] ?? key);
    if (changed.length > 0) {
      lines.push(
        `Edited "${itemLabel(item)}" — ${[...new Set(changed)].join(", ")}`,
      );
    }
  }
  const beforeOrder = before
    .map((item) => item.id)
    .filter((id) => afterIds.has(id));
  const afterOrder = after
    .map((item) => item.id)
    .filter((id) => beforeById.has(id));
  if (beforeOrder.join("\n") !== afterOrder.join("\n")) {
    lines.push("Reordered — the top item shows first");
  }
  return lines;
}

export function Editor({
  token,
  flag,
  onFlagUpdated,
  onLogout,
}: {
  token: string;
  flag: FlagRecord;
  onFlagUpdated: (flag: FlagRecord) => void;
  onLogout: () => void;
}) {
  const initial = useMemo(() => {
    const parsed = announcementsPayloadSchema.safeParse(readPayload(flag));
    return parsed.success
      ? { items: toEditable(parsed.data.announcements) }
      : null;
  }, [flag]);

  const [items, setItems] = useState<EditableItem[]>(initial?.items ?? []);
  const [selected, setSelected] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [published, setPublished] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);

  const flagUrl = `${POSTHOG_HOST}/project/${PROJECT_ID}/feature_flags/${flag.id}`;
  const rollout = rolloutLabel(flag);
  const selIndex = Math.min(selected, items.length - 1);
  const selectedItem = items[selIndex] ?? null;

  const payloadJson = useMemo(
    () => JSON.stringify({ announcements: items.map(toPayloadItem) }, null, 2),
    [items],
  );

  // The live payload, normalized through the same editor model so the diff
  // shows real changes rather than key-order or formatting noise.
  const liveJson = useMemo(
    () =>
      initial === null
        ? null
        : JSON.stringify(
            { announcements: initial.items.map(toPayloadItem) },
            null,
            2,
          ),
    [initial],
  );
  const dirty = liveJson !== payloadJson;

  const changes = useMemo(
    () => (initial === null ? [] : describeChanges(initial.items, items)),
    [initial, items],
  );

  useEffect(() => {
    if (!confirming) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) setConfirming(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirming, saving]);

  const update = (index: number, patch: Partial<EditableItem>) => {
    setItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
    setPublished(false);
  };

  const move = (index: number, delta: number) => {
    setItems((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setSelected(Math.max(0, Math.min(index + delta, items.length - 1)));
    setPublished(false);
  };

  const remove = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index));
    setSelected((prev) => Math.max(0, prev > index ? prev - 1 : prev));
    setPublished(false);
  };

  const add = (kind: EditableItem["kind"]) => {
    setItems((prev) => [...prev, { ...blankItem(kind), id: newItemId() }]);
    setSelected(items.length);
    setPublished(false);
  };

  const revert = () => {
    if (initial === null) return;
    capture("announcement admin changes reverted", {
      announcement_count: items.length,
      changed_item_count: changes.length,
      flag_id: flag.id,
    });
    setItems(initial.items);
    setSelected((index) =>
      Math.min(index, Math.max(0, initial.items.length - 1)),
    );
    setErrors([]);
    setPublished(false);
    setConfirming(false);
    setJsonDraft(null);
  };

  const applyJson = () => {
    if (jsonDraft === null) return;
    try {
      const parsed = announcementsPayloadSchema.parse(JSON.parse(jsonDraft));
      setItems(toEditable(parsed.announcements));
      setJsonDraft(null);
      setErrors([]);
    } catch (error) {
      setErrors(
        error instanceof z.ZodError
          ? error.issues.map((i) => `${i.path.join(".")}: ${i.message}`)
          : [String(error)],
      );
    }
  };

  // Publishing is two steps: validate and open the review modal, then write
  // the flag only from the modal's confirm button.
  const requestPublish = () => {
    const parsed = announcementsPayloadSchema.safeParse({
      announcements: items.map(toPayloadItem),
    });
    if (!parsed.success) {
      setErrors(
        parsed.error.issues.map(
          (i) => `announcements.${i.path.join(".")}: ${i.message}`,
        ),
      );
      return;
    }
    setErrors([]);
    capture("announcement admin changes reviewed", {
      announcement_count: items.length,
      changed_item_count: changes.length,
      flag_id: flag.id,
      has_required_update: items.some(
        (item) => item.kind === "required-update",
      ),
    });
    setConfirming(true);
  };

  const confirmPublish = async () => {
    const parsed = announcementsPayloadSchema.safeParse({
      announcements: items.map(toPayloadItem),
    });
    if (!parsed.success) return;
    setSaving(true);
    try {
      onFlagUpdated(await savePayload(token, flag, parsed.data));
      capture("announcement admin payload published", {
        announcement_count: items.length,
        changed_item_count: changes.length,
        flag_id: flag.id,
        has_required_update: items.some(
          (item) => item.kind === "required-update",
        ),
      });
      setConfirming(false);
      setPublished(true);
    } catch (error) {
      capture("announcement admin publish failed", { flag_id: flag.id });
      captureException(error);
      setErrors([String(error)]);
    } finally {
      setSaving(false);
    }
  };

  if (initial === null) {
    return (
      <div className="console">
        <p className="errors">
          The current flag payload does not match the announcements schema. Fix
          it on{" "}
          <a href={flagUrl} target="_blank" rel="noreferrer">
            the flag
          </a>{" "}
          and reload.
        </p>
      </div>
    );
  }

  return (
    <div className="console">
      <header className="masthead">
        <div>
          <span className="eyebrow">PostHog Desktop · internal</span>
          <h1>Announcements</h1>
        </div>
        <div className="masthead-status">
          <a
            className="flag-chip"
            href={flagUrl}
            target="_blank"
            rel="noreferrer"
          >
            posthog-desktop-announcements
          </a>
          <span className={rollout.live ? "pill pill-live" : "pill"}>
            <span className="pill-dot" aria-hidden />
            {rollout.text}
          </span>
          <button type="button" className="btn btn-ghost" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>

      <div className="layout">
        <aside className="rail">
          <div className="rail-list">
            {items.map((item, index) => (
              <div
                key={`${index}-${item.kind}`}
                className={
                  index === selIndex
                    ? "rail-item rail-item-active"
                    : "rail-item"
                }
              >
                <button
                  type="button"
                  className="rail-row"
                  onClick={() => setSelected(index)}
                >
                  <span className="rail-num">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span
                    className={
                      item.kind === "required-update"
                        ? "rail-dot rail-dot-update"
                        : "rail-dot"
                    }
                    title={
                      item.kind === "required-update"
                        ? "Required update"
                        : "Announcement"
                    }
                  />
                  <span className="rail-title">{item.title || "Untitled"}</span>
                </button>
                <span className="rail-actions">
                  <button
                    type="button"
                    aria-label="Move up"
                    onClick={() => move(index, -1)}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label="Move down"
                    onClick={() => move(index, 1)}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    aria-label="Remove"
                    onClick={() => remove(index)}
                  >
                    ✕
                  </button>
                </span>
              </div>
            ))}
          </div>
          <div className="rail-add">
            <button
              type="button"
              className="btn"
              onClick={() => add("announcement")}
            >
              + Announcement
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => add("required-update")}
            >
              + Required update
            </button>
          </div>
          <p className="rail-note">
            Top item shows first — one announcement per app session.
          </p>
        </aside>

        <main className="work">
          {selectedItem ? (
            <>
              <Stage
                item={selectedItem}
                onChange={(patch) => update(selIndex, patch)}
              />
              <div className="props">
                <label title="Dismissal key — persists per user; change it to resurface the announcement for everyone">
                  id
                  <input
                    className="mono"
                    placeholder="cloud-billing"
                    value={selectedItem.id}
                    onChange={(e) => update(selIndex, { id: e.target.value })}
                  />
                </label>
                <label
                  title={
                    selectedItem.kind === "required-update"
                      ? "Apps below this version are blocked until they update"
                      : "Optional — apps below this version see an Update button instead"
                  }
                >
                  min version
                  <input
                    className="mono"
                    placeholder="1.42.0"
                    value={selectedItem.minVersion}
                    onChange={(e) =>
                      update(selIndex, { minVersion: e.target.value })
                    }
                  />
                </label>
                <label title="Optional — hidden before this time">
                  starts
                  <input
                    type="datetime-local"
                    className="mono"
                    value={isoToLocalInput(selectedItem.startsAt)}
                    onChange={(e) =>
                      update(selIndex, {
                        startsAt: localInputToIso(e.target.value),
                      })
                    }
                  />
                </label>
                <label title="Optional — hidden after this time">
                  ends
                  <input
                    type="datetime-local"
                    className="mono"
                    value={isoToLocalInput(selectedItem.endsAt)}
                    onChange={(e) =>
                      update(selIndex, {
                        endsAt: localInputToIso(e.target.value),
                      })
                    }
                  />
                </label>
                {selectedItem.kind === "announcement" &&
                  !selectedItem.requiresAck && (
                    <label
                      className="props-grow"
                      title="Where the button goes — https:// opens the browser, posthog-code:// opens in-app"
                    >
                      button link
                      <input
                        className="mono"
                        placeholder="https:// or posthog-code://"
                        value={selectedItem.ctaUrl}
                        onChange={(e) =>
                          update(selIndex, { ctaUrl: e.target.value })
                        }
                      />
                    </label>
                  )}
              </div>
              <p className="facts">{factsFor(selectedItem)}</p>
            </>
          ) : (
            <p className="work-empty">
              Nothing queued — add an announcement to start.
            </p>
          )}

          {errors.length > 0 && !confirming && (
            <ul className="errors">
              {errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          )}

          <div className="row publish-row">
            {dirty && (
              <button type="button" className="btn" onClick={revert}>
                Revert
              </button>
            )}
            <button
              type="button"
              className="btn btn-publish"
              disabled={saving || !dirty}
              onClick={requestPublish}
            >
              Review changes
            </button>
            {published && <span className="publish-note">Published</span>}
          </div>

          <details className="json">
            <summary>Raw JSON</summary>
            <textarea
              rows={14}
              className="mono"
              value={jsonDraft ?? payloadJson}
              onChange={(e) => setJsonDraft(e.target.value)}
            />
            <button
              type="button"
              className="btn"
              disabled={jsonDraft === null}
              onClick={applyJson}
            >
              Apply JSON
            </button>
          </details>
        </main>
      </div>

      {confirming && liveJson !== null && (
        <div className="confirm-scrim">
          <div
            className="confirm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <h2 id="confirm-title">Review changes</h2>
            {changes.length > 0 && (
              <ul className="confirm-summary">
                {changes.map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
            )}
            <div className="diff-view confirm-diff">
              <MultiFileDiff
                oldFile={{ name: "payload.json", contents: liveJson }}
                newFile={{ name: "payload.json", contents: payloadJson }}
                options={DIFF_OPTIONS}
              />
            </div>
            {errors.length > 0 && (
              <ul className="errors">
                {errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            )}
            <div className="confirm-actions">
              <span className="spacer" />
              <button
                type="button"
                className="btn"
                onClick={() => setConfirming(false)}
                disabled={saving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-publish"
                onClick={() => void confirmPublish()}
                disabled={saving}
              >
                {saving ? "Publishing…" : "Publish"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
