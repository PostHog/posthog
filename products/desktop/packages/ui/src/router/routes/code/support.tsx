import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { FUTURE_SUPPORT_FLAG } from "@posthog/ui/features/support/featureFlag";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/code/support")({
  component: SupportGate,
});

/**
 * Gates the entire Support surface (queue + ticket detail) behind the
 * `future-support` flag. When disabled the sidebar item is also hidden;
 * direct navigation here lands on this placeholder.
 */
function SupportGate() {
  const enabled = useFeatureFlag(FUTURE_SUPPORT_FLAG, import.meta.env.DEV);
  if (!enabled) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center p-6">
        <span className="max-w-sm text-center text-[13px] text-gray-10 leading-snug">
          Support isn't available yet.
        </span>
      </div>
    );
  }
  return <Outlet />;
}
