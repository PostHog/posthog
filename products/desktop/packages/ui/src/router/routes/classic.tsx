import { ClassicView } from "@posthog/ui/features/classic/ClassicView";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/classic")({ component: ClassicView });
