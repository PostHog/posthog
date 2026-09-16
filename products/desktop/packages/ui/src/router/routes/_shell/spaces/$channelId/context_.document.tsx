import { ContextDocumentPage } from "@posthog/ui/features/canvas/components/context/ContextDocumentPage";
import {
  ChannelSkeleton,
  withRouteSkeleton,
} from "@posthog/ui/router/routeSkeletons";
import { createFileRoute } from "@tanstack/react-router";

// `context_` keeps this page out of the Context tab's outlet: it is a sibling
// screen with its own header, reached from the tab and leading back to it.
export const Route = createFileRoute(
  "/_shell/spaces/$channelId/context_/document",
)({
  validateSearch: (search: Record<string, unknown>) => ({
    edit: search.edit === true || search.edit === "true" ? true : undefined,
  }),
  component: ContextDocumentRoute,
  ...withRouteSkeleton(ChannelSkeleton),
});

function ContextDocumentRoute() {
  const { channelId } = Route.useParams();
  const { edit } = Route.useSearch();
  const navigate = Route.useNavigate();
  return (
    <ContextDocumentPage
      channelId={channelId}
      editing={edit === true}
      onEditingChange={(editing) =>
        void navigate({
          search: { edit: editing ? true : undefined },
          replace: true,
        })
      }
    />
  );
}
