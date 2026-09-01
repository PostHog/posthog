import { beforeEach, describe, expect, it } from "vitest";
import { useSettingsPageStore } from "./settingsPageStore";

describe("settingsPageStore", () => {
  beforeEach(() => {
    useSettingsPageStore.getState().reset();
  });

  it("starts with empty context and no initial action or form mode", () => {
    const s = useSettingsPageStore.getState();
    expect(s.context).toEqual({});
    expect(s.initialAction).toBeNull();
    expect(s.formMode).toBe(false);
  });

  it("setContext / clearContext write and clear", () => {
    useSettingsPageStore.getState().setContext({ repoPath: "/r" });
    expect(useSettingsPageStore.getState().context.repoPath).toBe("/r");
    useSettingsPageStore.getState().clearContext();
    expect(useSettingsPageStore.getState().context).toEqual({});
  });

  it("consumeInitialAction returns and clears the pending action", () => {
    useSettingsPageStore.getState().setInitialAction("create-new");
    expect(useSettingsPageStore.getState().consumeInitialAction()).toBe(
      "create-new",
    );
    expect(useSettingsPageStore.getState().initialAction).toBeNull();
  });

  it("setFormMode toggles formMode", () => {
    useSettingsPageStore.getState().setFormMode(true);
    expect(useSettingsPageStore.getState().formMode).toBe(true);
  });

  it("reset clears everything", () => {
    useSettingsPageStore.getState().setContext({ repoPath: "/r" });
    useSettingsPageStore.getState().setInitialAction("a");
    useSettingsPageStore.getState().setFormMode(true);
    useSettingsPageStore.getState().reset();
    const s = useSettingsPageStore.getState();
    expect(s.context).toEqual({});
    expect(s.initialAction).toBeNull();
    expect(s.formMode).toBe(false);
  });
});
