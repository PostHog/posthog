import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { type ToastOptions, toast } from "@posthog/ui/primitives/toast";

/**
 * A toast that teaches something, keyed so it stops once the lesson has landed.
 *
 * The alternative is a plain `toast.info`, which fires every single time the
 * thing it explains happens: the twentieth steer does not need to be told what
 * steering does. Same keyed `hints` the anchored tips answer to, so both stop
 * together from the tips switch in settings, and both come back from its reset.
 *
 * Reach for `TeachingTip` instead when the lesson is "this is where that went":
 * a toast in the corner cannot point at anything.
 */
export function hintToast(
  /** Stable key for this lesson, from `TIP_KEYS`. */
  key: string,
  title: string,
  detail?: string | ToastOptions,
): void {
  const store = useSettingsStore.getState();
  if (!store.shouldShowHint(key)) return;
  // Toasts off means this never reaches the screen, so don't spend the hint's
  // offer count on it; it is offered again once toasts come back on.
  if (!store.toastNotifications) return;
  store.recordHintShown(key);
  const options: ToastOptions =
    typeof detail === "string" ? { description: detail } : (detail ?? {});
  toast.info(title, {
    ...options,
    // A way to end the lesson now rather than sitting through its remaining
    // showings. Settings puts back anything hidden here.
    action: options.action ?? {
      label: "Hide",
      onClick: () => useSettingsStore.getState().markHintLearned(key),
    },
  });
}
