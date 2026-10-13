import { openNewLoop } from "@posthog/ui/features/loops/loopWizardDialogStore";
import { createFileRoute, Navigate } from "@tanstack/react-router";
import { useEffect } from "react";

export const Route = createFileRoute("/_shell/loops/new")({
  component: NewLoopRoute,
});

function NewLoopRoute() {
  useEffect(() => {
    openNewLoop();
  }, []);
  return <Navigate replace to="/loops" />;
}
