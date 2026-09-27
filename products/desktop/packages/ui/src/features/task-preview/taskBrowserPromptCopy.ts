import type {
  TaskBrowserPermissionDecision,
  TaskBrowserPermissionRequest,
} from "@posthog/platform/task-browser";
import { siteName } from "./browserAddress";

export type TaskBrowserPromptCopy = {
  title: string;
  description: string;
  detail: string | null;
  actions: Array<{
    label: string;
    decision: TaskBrowserPermissionDecision;
    variant: "primary" | "outline" | "default";
  }>;
};

const DENY = {
  label: "Don't allow",
  decision: "deny",
  variant: "default",
} as const;

export function taskBrowserPromptCopy(
  request: TaskBrowserPermissionRequest,
): TaskBrowserPromptCopy {
  const site = siteName(request.origin);
  switch (request.kind) {
    case "site":
      return {
        title: `Let the agent use ${site}?`,
        description:
          "The agent wants to open or read this site in the in-app browser. Page content can contain instructions meant to trick the agent, so allow only sites you trust for this task.",
        detail: null,
        actions: [
          { label: "Always block", decision: "block", variant: "default" },
          DENY,
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
        description: `The agent wants to do this on ${site}. It then acts as you on this site.`,
        detail: request.detail,
        actions: [
          DENY,
          { label: "Allow once", decision: "allow-once", variant: "primary" },
        ],
      };
    case "full-cdp":
      return {
        title: "Give the agent full DevTools access?",
        description: `The agent wants to run its own scripts and use DevTools on ${site} for the rest of this task. It can then read and change everything on this site, including network traffic, without asking again.`,
        detail: null,
        actions: [
          DENY,
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
        description: `The agent wants to do this on ${site}.`,
        detail: request.detail,
        actions: [
          DENY,
          { label: "Allow once", decision: "allow-once", variant: "primary" },
        ],
      };
  }
}
