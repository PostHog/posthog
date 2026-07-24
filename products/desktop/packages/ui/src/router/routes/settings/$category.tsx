import { SettingsPanel } from "@posthog/ui/features/settings/components/SettingsPanel";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { isSettingsCategory } from "@posthog/ui/features/settings/types";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/settings/$category")({
  component: SettingsRoute,
});

function SettingsRoute() {
  const { category } = Route.useParams();
  const cat = isSettingsCategory(category) ? category : "general";

  // Reset transient state when leaving the route entirely. Switching between
  // categories (e.g. general → environments) does not unmount this component,
  // only the cleanup on full unmount needs to fire.
  useEffect(() => {
    return () => useSettingsPageStore.getState().reset();
  }, []);

  return <SettingsPanel activeCategory={cat} />;
}
