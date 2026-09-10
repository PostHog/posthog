import { ACTIVITY_CANVAS_FLAG } from "@posthog/shared";
import { ActivityCanvasPane } from "@posthog/ui/features/canvas/components/ActivityCanvasPane";
import { ActivityDetailPane } from "@posthog/ui/features/canvas/components/ActivityDetailPane";
import { ActivityView } from "@posthog/ui/features/canvas/components/ActivityView";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useActivityCanvasStore } from "@posthog/ui/features/canvas/stores/activityCanvasStore";
import {
  type ActivitySearch,
  parseActivitySearch,
} from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
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
  const canvasEnabled = useFeatureFlag(ACTIVITY_CANVAS_FLAG);
  const canvasId = useActivityCanvasStore((state) => state.canvasId);
  const channelsLayout = useChannelsLayout();

  // A person who picked a canvas reads their activity through it instead. The
  // sidebar feed stays where the spaces layout draws one, so the built-in rows
  // are still one click away.
  if (canvasEnabled && canvasId) {
    return <ActivityCanvasPane canvasId={canvasId} />;
  }
  // Under the spaces layout the feed is the sidebar column (ChannelsSidebar
  // draws it for this route), so the pane beside it is whatever you picked from
  // the feed. Without that layout there is no such column and the page has to
  // carry the feed itself.
  return channelsLayout ? <ActivityDetailPane /> : <ActivityView />;
}
