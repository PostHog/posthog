import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { hintToast } from "./hintToast";

const quillToast = vi.hoisted(() => ({ info: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({ toast: quillToast }));

beforeEach(() => {
  vi.clearAllMocks();
  useSettingsStore.setState({
    hints: {},
    tipsEnabled: true,
    toastNotifications: true,
  });
});

describe("hintToast", () => {
  // A plain toast.info fires every time the thing it explains happens, so the
  // twentieth steer still gets told what steering does.
  it("stops offering a lesson after its last showing", () => {
    hintToast("a-lesson", "Steering waits", "It applies later", 1);
    hintToast("a-lesson", "Steering waits", "It applies later", 1);

    expect(quillToast.info).toHaveBeenCalledTimes(1);
  });

  it("stops offering a lesson once hidden, before its showings run out", () => {
    hintToast("a-lesson", "Steering waits", "It applies later");
    const options = quillToast.info.mock.calls[0][1];
    options.action.onClick();

    hintToast("a-lesson", "Steering waits", "It applies later");

    expect(quillToast.info).toHaveBeenCalledTimes(1);
    expect(useSettingsStore.getState().hints["a-lesson"]?.learned).toBe(true);
  });

  // With toasts off the tip never reaches the screen, so a max:1 lesson must not
  // burn its single offer; it comes back once toasts are on again.
  it("does not spend a showing while toast notifications are off", () => {
    useSettingsStore.setState({ toastNotifications: false });
    hintToast("a-lesson", "Steering waits", "It applies later", 1);

    expect(quillToast.info).not.toHaveBeenCalled();
    expect(useSettingsStore.getState().hints["a-lesson"]).toBeUndefined();

    useSettingsStore.setState({ toastNotifications: true });
    hintToast("a-lesson", "Steering waits", "It applies later", 1);

    expect(quillToast.info).toHaveBeenCalledTimes(1);
  });
});
