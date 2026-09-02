import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { hintToast } from "./hintToast";

/** One showing in `TIP_SHOWINGS`; the paste lesson gets three. */
const STEER = TIP_KEYS.steerSafeBoundary;
const PASTE = TIP_KEYS.pasteAsFile;

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
    hintToast(STEER, "Steering waits", "It applies later");
    hintToast(STEER, "Steering waits", "It applies later");

    expect(quillToast.info).toHaveBeenCalledTimes(1);
  });

  it("stops offering a lesson once hidden, before its showings run out", () => {
    hintToast(PASTE, "Pasted as a file", "It uploads with the message");
    const options = quillToast.info.mock.calls[0][1];
    options.action.onClick();

    hintToast(PASTE, "Pasted as a file", "It uploads with the message");

    expect(quillToast.info).toHaveBeenCalledTimes(1);
    expect(useSettingsStore.getState().hints[PASTE]?.learned).toBe(true);
  });

  // With toasts off the tip never reaches the screen, so the steer lesson must not
  // burn its one offer; it comes back once toasts are on again.
  it("does not spend a showing while toast notifications are off", () => {
    useSettingsStore.setState({ toastNotifications: false });
    hintToast(STEER, "Steering waits", "It applies later");

    expect(quillToast.info).not.toHaveBeenCalled();
    expect(useSettingsStore.getState().hints[STEER]).toBeUndefined();

    useSettingsStore.setState({ toastNotifications: true });
    hintToast(STEER, "Steering waits", "It applies later");

    expect(quillToast.info).toHaveBeenCalledTimes(1);
  });
});
