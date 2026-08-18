import {
  Code,
  MagnifyingGlass,
  PaperPlaneTilt,
  UserCircle,
} from "@phosphor-icons/react";
import type { SuggestedPrompt } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";

// Starter prompts for the agent panel on a support ticket. The ticket and its
// thread are already attached as context, so these read as follow-ups rather
// than the fill-in-the-blank templates the channels screen uses.
export const TICKET_AGENT_SUGGESTIONS: SuggestedPrompt[] = [
  {
    label: "Explain this ticket",
    description: "Summarize the problem and the likely cause",
    icon: MagnifyingGlass,
    color: "blue",
    mode: "auto",
    prompt:
      "Summarize this ticket: what the customer is reporting, what we have established so far, and the most likely cause. Flag anything we still need from them.",
  },
  {
    label: "Look up the customer",
    description: "Recent events, replays, and errors",
    icon: UserCircle,
    color: "violet",
    mode: "auto",
    prompt:
      "Look up this customer in PostHog. Pull their recent events, session replays, and errors around the time they reported this, and tell me what stands out.",
  },
  {
    label: "Find the code path",
    description: "Trace the behavior in the codebase",
    icon: Code,
    color: "orange",
    mode: "plan",
    prompt:
      "Trace this behavior through the PostHog codebase. Find the code path involved, tell me whether it is working as intended, and link the relevant files.",
  },
  {
    label: "Draft a reply",
    description: "Write a response for the customer",
    icon: PaperPlaneTilt,
    color: "green",
    mode: "auto",
    prompt:
      "Draft a reply to the customer for this ticket. Lead with the answer, keep it short, and only claim what the thread and the code support.",
  },
];
