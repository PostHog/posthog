import { useServiceOptional } from "@posthog/di/react";
import {
  type ITaskBrowserHost,
  TASK_BROWSER_HOST,
  type TaskBrowserPermissionDecision,
  type TaskBrowserPermissionRequest,
} from "@posthog/platform/task-browser";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useEffect, useState } from "react";
import { browserTabLabel, siteName } from "./browserAddress";

type PromptCopy = {
  title: string;
  description: string;
  actions: Array<{
    label: string;
    decision: TaskBrowserPermissionDecision;
    variant: "primary" | "outline" | "default";
  }>;
};

function promptCopy(request: TaskBrowserPermissionRequest): PromptCopy {
  const site = siteName(request.origin);
  switch (request.kind) {
    case "site":
      return {
        title: `Let the agent use ${site}?`,
        description:
          "The agent wants to open or read this site in the in-app browser. Page content can contain instructions meant to trick the agent, so allow only sites you trust for this task.",
        actions: [
          { label: "Block", decision: "block", variant: "default" },
          {
            label: "Always allow",
            decision: "allow-always",
            variant: "outline",
          },
          {
            label: "Allow for this task",
            decision: "allow-task",
            variant: "primary",
          },
        ],
      };
    case "sign-in":
      return {
        title: "Let the agent sign in?",
        description: `The agent wants to ${request.detail} on ${site}. It then acts as you on this site.`,
        actions: [
          { label: "Don't allow", decision: "deny", variant: "default" },
          { label: "Allow once", decision: "allow-once", variant: "primary" },
        ],
      };
    case "full-cdp":
      return {
        title: "Give the agent full DevTools access?",
        description: `The agent wants to use the Chrome DevTools Protocol on ${request.origin ? site : "this tab"} for the rest of this task. It can then read and change everything on the page, including network traffic, without asking again.`,
        actions: [
          { label: "Don't allow", decision: "deny", variant: "default" },
          {
            label: "Allow for this task",
            decision: "allow-task",
            variant: "primary",
          },
        ],
      };
    case "sensitive-action":
      return {
        title: "Confirm this action",
        description: `The agent wants to ${request.detail} on ${site}.`,
        actions: [
          { label: "Don't allow", decision: "deny", variant: "default" },
          { label: "Allow once", decision: "allow-once", variant: "primary" },
        ],
      };
  }
}

export function TaskBrowserBridge() {
  const host = useServiceOptional<ITaskBrowserHost>(TASK_BROWSER_HOST);
  const [queue, setQueue] = useState<TaskBrowserPermissionRequest[]>([]);

  useEffect(() => {
    if (!host) return;
    const stopOpen = host.onOpenRequest((request) => {
      const store = usePanelLayoutStore.getState();
      store.openBrowserTab(request.taskId, {
        browserId: request.browserId,
        url: request.url,
        label: browserTabLabel(request.url),
      });
    });
    const stopClose = host.onCloseRequest((request) => {
      usePanelLayoutStore
        .getState()
        .closeBrowserTab(request.taskId, request.browserId);
    });
    const stopPermission = host.onPermissionRequest((request) => {
      setQueue((current) => [...current, request]);
    });
    const stopSettled = host.onPermissionSettled((requestId) => {
      setQueue((current) =>
        current.filter((request) => request.requestId !== requestId),
      );
    });
    return () => {
      stopOpen();
      stopClose();
      stopPermission();
      stopSettled();
    };
  }, [host]);

  const current = queue[0];
  if (!host || !current) return null;
  const copy = promptCopy(current);
  const answer = (decision: TaskBrowserPermissionDecision) => {
    setQueue((pending) => pending.slice(1));
    void host.respondToPermission(current.requestId, decision);
  };

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open) answer("deny");
      }}
    >
      <AlertDialogContent data-attr="task-browser-permission">
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.title}</AlertDialogTitle>
          <AlertDialogDescription>{copy.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {copy.actions.map((action) => (
            <Button
              key={action.decision}
              variant={action.variant}
              size="default"
              data-attr={`task-browser-permission-${action.decision}`}
              onClick={() => answer(action.decision)}
            >
              {action.label}
            </Button>
          ))}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
