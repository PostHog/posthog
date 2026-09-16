import { ShellLayout } from "@posthog/ui/features/canvas/components/ShellLayout";
import { useShellOwnsHeader } from "@posthog/ui/features/canvas/hooks/useShellOwnsHeader";
import { createFileRoute, Outlet } from "@tanstack/react-router";

/**
 * Pathless layout for the routes that wear the spaces chrome — Home, Activity,
 * the spaces themselves, and the pages the rail reaches beside them.
 *
 * Pathless because the chrome used to be inferred from a `/website` prefix, and
 * flattening the routes took that prefix away. Grouping them here keeps the
 * layout without putting a segment in every URL.
 */
export const Route = createFileRoute("/_shell")({
  component: ShellRoute,
});

function ShellRoute() {
  // Outside the channels world these same routes render bare and the root's
  // ContentHeader carries the title, which is what they did before the flatten.
  return useShellOwnsHeader() ? <ShellLayout /> : <Outlet />;
}
