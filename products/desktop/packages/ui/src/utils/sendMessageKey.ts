import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

interface SubmitKeyEvent {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
}

export function isSendMessageSubmitKey(event: SubmitKeyEvent): boolean {
  if (event.key !== "Enter") return false;
  const sendMessagesWith = useSettingsStore.getState().sendMessagesWith;
  if (sendMessagesWith === "cmd+enter") {
    return event.metaKey || event.ctrlKey;
  }
  return !event.shiftKey;
}
