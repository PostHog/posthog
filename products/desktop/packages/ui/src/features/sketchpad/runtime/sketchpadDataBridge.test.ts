import {
  applyOp,
  emptySketchpadSnapshot,
  materializeList,
  SKETCHPAD_FIELD_MAX_ENTRIES,
  type SketchpadField,
} from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import {
  handleSketchpadDataRequest,
  type SketchpadDataBridgeContext,
} from "./sketchpadDataBridge";

it.each(["remote edit", "restore", "invalid stored entry"])(
  "keeps current field data after %s",
  async (change) => {
    let snapshot = emptySketchpadSnapshot();
    const ctx: SketchpadDataBridgeContext = {
      sketchpadId: change,
      queryClient: new QueryClient(),
      getSnapshot: () => snapshot,
      applyLocal: (ops) => {
        for (const op of ops) snapshot = applyOp(snapshot, op);
      },
      reportCaret: vi.fn(),
    };
    const edit = (payload: object) =>
      handleSketchpadDataRequest(
        "stateEditList",
        { key: "items", ...payload },
        ctx,
      );
    await edit({ insert: [{ value: "initial" }] });
    const saved = snapshot;
    const field = snapshot.state.items as SketchpadField;
    const [id] = Object.keys(field.entries);
    if (change === "restore") {
      await edit({ remove: [id] });
      snapshot = applyOp(snapshot, {
        type: "restore",
        snapshot: saved,
        toSeq: 1,
      });
    } else if (change === "invalid stored entry") {
      snapshot = applyOp(snapshot, {
        type: "set_state",
        key: "items",
        value: { ...field, entries: { ...field.entries, bad: null } },
      });
    } else {
      snapshot = applyOp(snapshot, {
        type: "edit_field",
        key: "items",
        kind: "list",
        insert: [{ id, k: field.entries[id].k, v: "remote" }],
      });
    }
    const answer = await edit({
      update: [{ id: "bad", value: "ignored" }],
      insert: [{ afterId: id, value: "addition" }],
    });
    const items = materializeList(snapshot.state.items as SketchpadField);
    expect(items.map((item) => item.value)).toEqual([
      change === "remote edit" ? "remote" : "initial",
      "addition",
    ]);
    expect(answer).toEqual({ items });
  },
);

it.each(["a", "🙂"])(
  "rejects oversized text before writing: %s",
  async (character) => {
    const applyLocal = vi.fn();
    await expect(
      handleSketchpadDataRequest(
        "stateEditText",
        {
          key: "note",
          base: "",
          baseIds: [],
          next: character.repeat(SKETCHPAD_FIELD_MAX_ENTRIES + 1),
        },
        {
          sketchpadId: character,
          queryClient: new QueryClient(),
          getSnapshot: emptySketchpadSnapshot,
          applyLocal,
          reportCaret: vi.fn(),
        },
      ),
    ).rejects.toThrow();
    expect(applyLocal).not.toHaveBeenCalled();
  },
);

it.each(["text", "list"] as const)(
  "edits and resets plain %s values with a long key",
  async (kind) => {
    const key = "n".repeat(128);
    let snapshot = emptySketchpadSnapshot();
    const ctx: SketchpadDataBridgeContext = {
      sketchpadId: kind,
      queryClient: new QueryClient(),
      getSnapshot: () => snapshot,
      applyLocal: (ops) => {
        for (const op of ops) snapshot = applyOp(snapshot, op);
      },
      reportCaret: vi.fn(),
    };
    for (const initial of ["A", "", "A"]) {
      snapshot = applyOp(snapshot, {
        type: "set_state",
        key,
        value: kind === "text" ? initial : initial ? [initial] : [],
      });
      const answer = await handleSketchpadDataRequest(
        kind === "text" ? "stateEditText" : "stateEditList",
        kind === "text"
          ? {
              key,
              base: initial,
              baseIds: initial ? ["seed-0"] : [],
              next: "B",
            }
          : {
              key,
              remove: initial ? ["seed-0"] : [],
              insert: [{ value: "B" }],
            },
        ctx,
      );
      expect(answer).toMatchObject(
        kind === "text" ? { text: "B" } : { items: [{ value: "B" }] },
      );
      expect(
        await handleSketchpadDataRequest("stateGet", { key }, ctx),
      ).toEqual(kind === "text" ? "B" : ["B"]);
    }
  },
);
