import { ReportsTab } from "@posthog/ui/features/inbox/components/ReportsTab";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/code/inbox/reports/")({
  component: ReportsTab,
});
