import {
  SKETCHPAD_MAX_READS_IN_FLIGHT,
  SKETCHPAD_MAX_READS_WAITING,
  SKETCHPAD_READ_LIMIT,
  SKETCHPAD_WRITE_LIMIT,
  TokenBucket,
} from "@posthog/core/sketchpad/frameBudget";
import {
  applyOp,
  diffTextToOps,
  emptyField,
  emptySketchpadSnapshot,
  estimateJsonBytes,
  fieldOrder,
  isField,
  isFieldEntry,
  isReservedStateKey,
  keyBetween,
  materializeList,
  materializeText,
  newEntryId,
  SKETCHPAD_FIELD_MARK,
  SKETCHPAD_FIELD_MAX_ENTRIES,
  SKETCHPAD_FIELD_MAX_OP_ENTRIES,
  SKETCHPAD_FIELD_MAX_REMOVED,
  SKETCHPAD_MAX_STATE_VALUE_BYTES,
  SKETCHPAD_STATE_KEY_MAX_CHARS,
  type SketchpadDataMethod,
  type SketchpadField,
  type SketchpadFieldKind,
  type SketchpadFragmentPatch,
  type SketchpadOp,
  type SketchpadPresenceCaret,
  type SketchpadSnapshot,
} from "@posthog/shared";
import { handleFreeformDataRequest } from "@posthog/ui/features/canvas/freeform/freeformDataBridge";
import { fieldPlainValue } from "@posthog/ui/features/sketchpad/runtime/sketchpadFieldMessages";
import {
  SHARED_FIELD_READ_ONLY_STATE,
  SHARED_TEXT_CHANGES_FULL,
  SHARED_TEXT_FULL,
  SKETCHPAD_TOO_MANY_READS_AT_ONCE,
  sketchpadReadsPausedMessage,
  sketchpadWritesPausedMessage,
} from "@posthog/ui/features/sketchpad/sketchpadCopy";
import type { QueryClient } from "@tanstack/react-query";

export interface SketchpadDataBridgeContext {
  signal?: AbortSignal;
  sketchpadId: string;
  queryClient: QueryClient;
  getSnapshot: () => SketchpadSnapshot;
  applyLocal: (ops: SketchpadOp[], opIds?: string[]) => void;
  reportCaret: (caret: SketchpadPresenceCaret | null) => void;
}

interface SketchpadTextEditPayload {
  base?: unknown;
  baseIds?: unknown;
  next?: unknown;
  caret?: unknown;
}

interface SketchpadListEditPayload {
  insert?: unknown;
  remove?: unknown;
  update?: unknown;
}

interface SketchpadBudget {
  reads: TokenBucket;
  writes: TokenBucket;
  readsInFlight: number;
  waiting: (() => void)[];
}

const budgets = new Map<string, SketchpadBudget>();

const BRIDGE_CLIENT_ID = globalThis.crypto.randomUUID().replace(/-/g, "");
let entryCounter = 0;

const SEED_KEY_HEAD = "d";
const SEED_KEY_WIDTH = 4;
const SEED_KEY_DIGITS =
  "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

export async function handleSketchpadDataRequest(
  method: SketchpadDataMethod,
  payload: unknown,
  ctx: SketchpadDataBridgeContext,
): Promise<unknown> {
  switch (method) {
    case "query":
    case "loadInsight":
      return read(ctx, () =>
        handleFreeformDataRequest(method, payload, ctx.queryClient),
      );
    case "stateGet": {
      const key = readKey(payload, "ph.state.get(key) requires a key");
      return fieldPlainValue(ctx.getSnapshot().state[key] ?? null);
    }
    case "stateSet": {
      const key = readKey(payload, "ph.state.set(key, value) requires a key");
      if (isField(ctx.getSnapshot().state[key])) {
        throw new Error(SHARED_FIELD_READ_ONLY_STATE);
      }
      const raw = (payload as { value?: unknown }).value;
      const value = raw === undefined ? null : raw;
      if (estimateJsonBytes(value) > SKETCHPAD_MAX_STATE_VALUE_BYTES) {
        throw new Error(
          `ph.state.set(key, value) is limited to ${Math.floor(SKETCHPAD_MAX_STATE_VALUE_BYTES / 1024)} KB per value`,
        );
      }
      spendWrite(ctx);
      ctx.applyLocal([{ type: "set_state", key, value }]);
      return { ok: true };
    }
    case "stateList":
      return Object.entries(ctx.getSnapshot().state).map(([key, value]) => ({
        key,
        value: fieldPlainValue(value),
      }));
    case "stateEditText":
      return editText(payload, ctx);
    case "stateEditList":
      return editList(payload, ctx);
    case "arrangeFragments":
      return arrangeFragments(payload, ctx);
    default:
      throw new Error(`ph.${method} is not available on sketchpads yet`);
  }
}

const ARRANGE_MAX_ITEMS = 200;
const FRAGMENT_MIN_WIDTH = 80;
const FRAGMENT_MIN_HEIGHT = 60;
const FRAGMENT_MAX_SIZE = 4000;

interface ArrangeItem {
  id?: unknown;
  x?: unknown;
  y?: unknown;
  w?: unknown;
  h?: unknown;
  hidden?: unknown;
}

function arrangeFragments(
  payload: unknown,
  ctx: SketchpadDataBridgeContext,
): { moved: number } {
  const raw = (payload as { items?: unknown } | null)?.items;
  if (!Array.isArray(raw)) {
    throw new Error("ph.board.arrange(items) requires a list of fragments");
  }
  const known = new Map(
    ctx.getSnapshot().fragments.map((fragment) => [fragment.id, fragment]),
  );
  const ops: SketchpadOp[] = [];
  for (const entry of raw.slice(0, ARRANGE_MAX_ITEMS)) {
    if (typeof entry !== "object" || entry === null) continue;
    const item = entry as ArrangeItem;
    const id = typeof item.id === "string" ? item.id : "";
    const current = known.get(id);
    if (!current) continue;
    const wasHidden = current.hidden === true;
    const hidden = typeof item.hidden === "boolean" ? item.hidden : wasHidden;
    const patch: SketchpadFragmentPatch = {
      x: round(item.x, current.x),
      y: round(item.y, current.y),
      w: clamp(item.w, current.w, FRAGMENT_MIN_WIDTH),
      h: clamp(item.h, current.h, FRAGMENT_MIN_HEIGHT),
    };
    if (
      patch.x === current.x &&
      patch.y === current.y &&
      patch.w === current.w &&
      patch.h === current.h &&
      hidden === wasHidden
    ) {
      continue;
    }
    if (hidden !== wasHidden) patch.hidden = hidden;
    ops.push({ type: "update_fragment", id, patch });
  }
  if (ops.length === 0) return { moved: 0 };
  spendWrite(ctx);
  ctx.applyLocal(ops);
  return { moved: ops.length };
}

function round(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.round(value)
    : Math.round(fallback);
}

function clamp(value: unknown, fallback: number, min: number): number {
  const next = round(value, fallback);
  return Math.min(FRAGMENT_MAX_SIZE, Math.max(min, next));
}

function editText(
  payload: unknown,
  ctx: SketchpadDataBridgeContext,
): { text: string; ids: string[] } {
  spendWrite(ctx);
  const key = readKey(payload, "ph.state.editText(key, edit) requires a key");
  const input = (payload ?? {}) as SketchpadTextEditPayload;
  const next = readString(input.next);
  if (
    next.length > SKETCHPAD_FIELD_MAX_ENTRIES * 2 ||
    (next.length > SKETCHPAD_FIELD_MAX_ENTRIES &&
      Array.from(next).length > SKETCHPAD_FIELD_MAX_ENTRIES)
  ) {
    throw new Error(SHARED_TEXT_FULL);
  }
  const field = readyField(ctx, key, "text");
  const sent = {
    text: readString(input.base),
    ids: readStrings(input.baseIds),
  };
  const base =
    sent.ids.length === sent.text.length ? sent : materializeText(field);
  const diff = diffTextToOps({
    base: base.text,
    baseIds: base.ids,
    next,
    field,
    key,
    clientId: BRIDGE_CLIENT_ID,
    counterStart: entryCounter,
  });
  refuseWhenFull(field, diff.ops);
  entryCounter = diff.counterEnd;
  const after = commit(ctx, key, field, diff.ops);
  const view = materializeText(after);
  ctx.reportCaret(caretOf(key, view.ids, input.caret));
  return view;
}

function editList(
  payload: unknown,
  ctx: SketchpadDataBridgeContext,
): { items: { id: string; value: unknown }[] } {
  spendWrite(ctx);
  const key = readKey(payload, "ph.state.editList(key, edit) requires a key");
  const input = (payload ?? {}) as SketchpadListEditPayload;
  const field = readyField(ctx, key, "list");
  const ops = listOps(key, field, input);
  refuseWhenFull(field, ops);
  const after = commit(ctx, key, field, ops);
  return { items: materializeList(after) };
}

function caretOf(
  key: string,
  ids: string[],
  raw: unknown,
): SketchpadPresenceCaret | null {
  if (typeof raw !== "object" || raw === null) return null;
  const caret = raw as { anchor?: unknown; focus?: unknown };
  return {
    key,
    anchor: idAt(ids, caret.anchor),
    focus: idAt(ids, caret.focus),
  };
}

function idAt(ids: string[], offset: unknown): string | null {
  if (typeof offset !== "number" || offset < 0) return null;
  return offset < ids.length ? ids[offset] : null;
}

function listOps(
  key: string,
  field: SketchpadField,
  input: SketchpadListEditPayload,
): SketchpadOp[] {
  const rows = fieldOrder(field);
  const insert: NonNullable<
    Extract<SketchpadOp, { type: "edit_field" }>["insert"]
  > = [];

  for (const change of readRecords(input.update)) {
    const id = typeof change.id === "string" ? change.id : "";
    const entry = field.entries[id];
    if (!isFieldEntry(entry)) continue;
    insert.push({ id, k: entry.k, v: change.value });
  }

  for (const change of readRecords(input.insert)) {
    const anchor = typeof change.afterId === "string" ? change.afterId : null;
    const at =
      anchor === null ? -1 : rows.findIndex((row) => row.id === anchor);
    const after = anchor !== null && at === -1 ? rows.length - 1 : at;
    const left = after >= 0 ? rows[after].entry.k : null;
    const right = after + 1 < rows.length ? rows[after + 1].entry.k : null;
    const entry = { k: keyBetween(left, right), v: change.value };
    const id = newEntryId(BRIDGE_CLIENT_ID, entryCounter++);
    rows.splice(after + 1, 0, { id, entry });
    insert.push({ id, k: entry.k, v: change.value });
  }

  const remove = readStrings(input.remove);
  if (insert.length === 0 && remove.length === 0) return [];
  return [
    {
      type: "edit_field",
      key,
      kind: "list",
      insert: insert.slice(0, SKETCHPAD_FIELD_MAX_OP_ENTRIES),
      remove: remove.slice(0, SKETCHPAD_FIELD_MAX_OP_ENTRIES),
    },
  ];
}

function commit(
  ctx: SketchpadDataBridgeContext,
  key: string,
  field: SketchpadField,
  ops: SketchpadOp[],
): SketchpadField {
  if (ops.length === 0) return field;
  const after = foldField(key, field, ops);
  ctx.applyLocal(ops);
  return after;
}

function refuseWhenFull(field: SketchpadField, ops: SketchpadOp[]): void {
  let inserted = 0;
  let removed = 0;
  for (const op of ops) {
    if (op.type !== "edit_field") continue;
    inserted += op.insert?.length ?? 0;
    removed += op.remove?.length ?? 0;
  }
  const live = Object.keys(field.entries).length;
  if (live + inserted > SKETCHPAD_FIELD_MAX_ENTRIES) {
    throw new Error(SHARED_TEXT_FULL);
  }
  if (field.removed.length + removed > SKETCHPAD_FIELD_MAX_REMOVED) {
    throw new Error(SHARED_TEXT_CHANGES_FULL);
  }
}

function readyField(
  ctx: SketchpadDataBridgeContext,
  key: string,
  kind: SketchpadFieldKind,
): SketchpadField {
  const live = ctx.getSnapshot().state[key];
  if (!isField(live)) {
    const ops = seedOps(key, kind, live);
    if (ops.length > 0) {
      const seeded = foldField(key, emptyField(kind), ops);
      ctx.applyLocal(ops);
      return seeded;
    }
  }
  return isField(live) && live[SKETCHPAD_FIELD_MARK] === kind
    ? live
    : emptyField(kind);
}

function seedOps(
  key: string,
  kind: SketchpadFieldKind,
  value: unknown,
): SketchpadOp[] {
  const parts: unknown[] | undefined =
    kind === "text" && typeof value === "string"
      ? Array.from(value)
      : kind === "list" && Array.isArray(value)
        ? value
        : undefined;
  if (!parts) return [];
  if (parts.length > SKETCHPAD_FIELD_MAX_ENTRIES)
    throw new Error(SHARED_TEXT_FULL);
  const entries = parts.map((part, index) => ({
    id: newEntryId("seed", index),
    k: seedKey(index),
    v: part,
  }));
  const ops: SketchpadOp[] = [];
  for (
    let at = 0;
    at < Math.max(entries.length, 1);
    at += SKETCHPAD_FIELD_MAX_OP_ENTRIES
  ) {
    ops.push({
      type: "edit_field",
      key,
      kind,
      initialValue: value,
      insert: entries.slice(at, at + SKETCHPAD_FIELD_MAX_OP_ENTRIES),
    });
  }
  return ops;
}

function seedKey(index: number): string {
  let digits = "";
  let rest = index;
  for (let at = 0; at < SEED_KEY_WIDTH; at++) {
    digits = SEED_KEY_DIGITS[rest % SEED_KEY_DIGITS.length] + digits;
    rest = Math.floor(rest / SEED_KEY_DIGITS.length);
  }
  return SEED_KEY_HEAD + digits;
}

function foldField(
  key: string,
  field: SketchpadField,
  ops: SketchpadOp[],
): SketchpadField {
  let carrier: SketchpadSnapshot = {
    ...emptySketchpadSnapshot(),
    state: { [key]: field },
  };
  for (const op of ops) carrier = applyOp(carrier, op);
  const next = carrier.state[key];
  return isField(next) ? next : field;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function readRecords(
  value: unknown,
): { id?: unknown; afterId?: unknown; value: unknown }[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is { id?: unknown; afterId?: unknown; value: unknown } =>
      typeof item === "object" && item !== null,
  );
}

function budgetOf(sketchpadId: string): SketchpadBudget {
  const existing = budgets.get(sketchpadId);
  if (existing) return existing;
  const now = Date.now();
  const fresh: SketchpadBudget = {
    reads: new TokenBucket(SKETCHPAD_READ_LIMIT, now),
    writes: new TokenBucket(SKETCHPAD_WRITE_LIMIT, now),
    readsInFlight: 0,
    waiting: [],
  };
  budgets.set(sketchpadId, fresh);
  return fresh;
}

async function read<T>(
  ctx: SketchpadDataBridgeContext,
  run: () => Promise<T>,
): Promise<T> {
  const budget = budgetOf(ctx.sketchpadId);
  const now = Date.now();
  if (!budget.reads.take(now)) {
    throw new Error(sketchpadReadsPausedMessage(budget.reads.waitSeconds(now)));
  }
  if (budget.waiting.length >= SKETCHPAD_MAX_READS_WAITING) {
    throw new Error(SKETCHPAD_TOO_MANY_READS_AT_ONCE);
  }
  await acquireReadSlot(budget, ctx.signal);
  try {
    if (ctx.signal?.aborted) throw ctx.signal.reason;
    return await run();
  } finally {
    releaseReadSlot(budget);
  }
}

function acquireReadSlot(
  budget: SketchpadBudget,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) return Promise.reject(signal.reason);
  if (budget.readsInFlight < SKETCHPAD_MAX_READS_IN_FLIGHT) {
    budget.readsInFlight += 1;
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    const ready = () => {
      signal?.removeEventListener("abort", abort);
      resolve();
    };
    const abort = () => {
      const index = budget.waiting.indexOf(ready);
      if (index !== -1) budget.waiting.splice(index, 1);
      reject(signal?.reason);
    };
    signal?.addEventListener("abort", abort, { once: true });
    budget.waiting.push(ready);
  });
}

function releaseReadSlot(budget: SketchpadBudget): void {
  const next = budget.waiting.shift();
  if (next) {
    next();
    return;
  }
  budget.readsInFlight -= 1;
}

function spendWrite(ctx: SketchpadDataBridgeContext): void {
  const budget = budgetOf(ctx.sketchpadId);
  const now = Date.now();
  if (budget.writes.take(now)) return;
  throw new Error(sketchpadWritesPausedMessage(budget.writes.waitSeconds(now)));
}

export function spendSketchpadWrite(sketchpadId: string): boolean {
  return budgetOf(sketchpadId).writes.take(Date.now());
}

function readKey(payload: unknown, message: string): string {
  const key = (payload as { key?: unknown } | null)?.key;
  if (typeof key !== "string" || key.length === 0) throw new Error(message);
  if (key.length > SKETCHPAD_STATE_KEY_MAX_CHARS) {
    throw new Error(
      `A state key holds at most ${SKETCHPAD_STATE_KEY_MAX_CHARS} characters`,
    );
  }
  if (isReservedStateKey(key)) {
    throw new Error(`"${key}" is reserved and cannot be a state key`);
  }
  return key;
}
