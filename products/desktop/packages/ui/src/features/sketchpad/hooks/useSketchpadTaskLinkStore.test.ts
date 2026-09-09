import { expect, it, vi } from "vitest";

const { values } = vi.hoisted(() => ({ values: new Map<string, string>() }));
vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  stateStorage: {
    getItem: async (key: string) => values.get(key) ?? null,
    setItem: async (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: async (key: string) => {
      values.delete(key);
    },
  },
}));

it("migrates task links before viewport storage can overwrite them", async () => {
  values.set(
    "posthog-code-sketchpad-viewports",
    JSON.stringify({
      state: {
        boards: {
          board: { taskId: "task", viewport: { x: 0, y: 0, zoom: 1 } },
        },
      },
      version: 0,
    }),
  );
  const { sketchpadIdForTask, useSketchpadTaskLinkStore } = await import(
    "./useSketchpadTaskLinkStore"
  );
  expect(await sketchpadIdForTask("task")).toBe("board");
  values.set(
    "posthog-code-sketchpad-viewports",
    JSON.stringify({ state: { boards: {} }, version: 0 }),
  );
  await useSketchpadTaskLinkStore.persist.rehydrate();
  expect(await sketchpadIdForTask("task")).toBe("board");
  expect(
    JSON.parse(values.get("posthog-code-sketchpad-task-links") ?? "{}").state
      .taskBySketchpad,
  ).toEqual({ board: "task" });
});
