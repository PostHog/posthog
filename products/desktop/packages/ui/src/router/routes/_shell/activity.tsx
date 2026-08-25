import { ActivityDetailPane } from "@posthog/ui/features/canvas/components/ActivityDetailPane";
import { ActivityView } from "@posthog/ui/features/canvas/components/ActivityView";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type ActivitySearch,
  parseActivitySearch,
} from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { createFileRoute } from "@tanstack/react-router";

// Activity: every task the viewer is involved in — created, @-mentioned in, or
// messaged in — across spaces. The rail's Activity badge counts what's new here.
export const Route = createFileRoute("/_shell/activity")({
  // The picked item lives in the search rather than a store, so the location
  // says what the pane is showing: a tab can then name it and restore it.
  validateSearch: (search: Record<string, unknown>): ActivitySearch =>
    parseActivitySearch(search),
  component: ActivityRoute,
});

function ActivityRoute() {
  // Under the spaces layout the feed is the sidebar column (ChannelsSidebar
  // draws it for this route), so the pane beside it is whatever you picked from
  // the feed. Without that layout there is no such column and the page has to
  // carry the feed itself.
  return useChannelsLayout() ? <ActivityDetailPane /> : <ActivityView />;
}
