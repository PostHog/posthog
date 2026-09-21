import { ReportsTab } from "@posthog/ui/features/inbox/components/ReportsTab";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/inbox/reports/")({
  component: ReportsTab,
});
