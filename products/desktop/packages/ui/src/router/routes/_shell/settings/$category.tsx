import { AnnouncementBanner } from "@posthog/ui/features/announcements/AnnouncementBanner";
import { ConnectivityBanner } from "@posthog/ui/features/connectivity/ConnectivityBanner";
import { SettingsPanel } from "@posthog/ui/features/settings/components/SettingsPanel";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { resolveSettingsCategory } from "@posthog/ui/features/settings/types";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";
import { createPortal } from "react-dom";

// Nested under `_shell` so the sidebar, tab strip and panels stay mounted while
// settings covers them; leaving settings then costs one tab switch instead of
// rebuilding the whole shell.
export const Route = createFileRoute("/_shell/settings/$category")({
  component: SettingsRoute,
});

function SettingsRoute() {
  const { category } = Route.useParams();
  const cat = resolveSettingsCategory(category) ?? "general";

  // Reset transient state when leaving the route entirely. Switching between
  // categories (e.g. general → environments) does not unmount this component,
  // only the cleanup on full unmount needs to fire.
  useEffect(() => {
    return () => useSettingsPageStore.getState().reset();
  }, []);

  // Portalling to document.body would land outside the Radix <Theme> subtree.
  const container =
    document.getElementById("portal-container") ?? document.body;

  return createPortal(
    <div
      className="absolute inset-0 z-[100] flex flex-col bg-(--color-background)"
      data-overlay="settings"
    >
      {/* The shell's copies are covered by this overlay and inert, so the
          banners move here for the duration: losing connectivity while
          settings is open must still show the offline state and its Retry. */}
      <ConnectivityBanner />
      <AnnouncementBanner />
      <div className="flex min-h-0 flex-1">
        <SettingsPanel activeCategory={cat} />
      </div>
    </div>,
    container,
  );
}
