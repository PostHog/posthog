import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import type {
  AgentsPageSearch,
  AgentsTab,
} from "@posthog/ui/features/agents/agentsPageStore";
import { SettingsLayout } from "@posthog/ui/features/settings/components/SettingsLayout";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { resolveSettingsCategory } from "@posthog/ui/features/settings/types";
import { validSourceHref } from "@posthog/ui/router/reportNavigation";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";

// Nested under `_shell` so the sidebar, tab strip and panels stay mounted while
// settings covers them; leaving settings then costs one tab switch instead of
// rebuilding the whole shell.
export const Route = createFileRoute("/_shell/settings/$category")({
  component: SettingsRoute,
  validateSearch: (search: Record<string, unknown>): AgentsPageSearch => {
    const text = (value: unknown) =>
      typeof value === "string" ? value : undefined;
    return {
      from: validSourceHref(search.from),
      tab: text(search.tab) as AgentsTab | undefined,
      agent: text(search.agent),
      agentTab: text(search.agentTab) as ScoutDetailTab | undefined,
      finding: text(search.finding),
    };
  },
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

  return <SettingsLayout category={cat} />;
}
