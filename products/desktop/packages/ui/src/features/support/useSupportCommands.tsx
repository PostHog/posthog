import {
  ArrowSquareOutIcon,
  ChatCircleIcon,
  CheckCircleIcon,
  ClockIcon,
  LifebuoyIcon,
  NotePencilIcon,
  PushPinIcon,
  RobotIcon,
  UserIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import { isTicketSnoozed } from "@posthog/core/support/ticketState";
import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useSupportFlag } from "@posthog/ui/features/feature-flags/useSupportFlag";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import { usePinnedTicketsStore } from "@posthog/ui/features/support/pinnedTicketsStore";
import { getCachedSupportTicket } from "@posthog/ui/features/support/supportQueries";
import {
  type SupportAssigneeScope,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { TICKET_PRIORITY_LABELS } from "@posthog/ui/features/support/ticketPresentation";
import { navigateToSupport } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { useMemo } from "react";

interface SupportCommand {
  id: string;
  label: string;
  keywords?: string;
  icon: React.ReactNode;
  action: CommandMenuAction;
  onRun: () => void;
}

const SNOOZE_MS = 24 * 60 * 60 * 1000;

const SCOPE_COMMANDS: Array<{ scope: SupportAssigneeScope; label: string }> = [
  { scope: "me", label: "Support: my tickets" },
  { scope: "unassigned", label: "Support: unassigned tickets" },
  { scope: "all", label: "Support: all tickets" },
];

const STATUS_COMMANDS: Array<{
  status: Schemas.TicketStatusEnum;
  label: string;
}> = [
  { status: "open", label: "Set ticket to open" },
  { status: "pending", label: "Set ticket to pending" },
  { status: "resolved", label: "Resolve ticket" },
];

export function useSupportCommands(closeSettingsDialog: () => void) {
  const supportEnabled = useSupportFlag();
  const view = useAppView();
  const updateTicket = useUpdateSupportTicket();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const currentUserId = currentUser?.id;

  const ticketId = view.type === "support" ? view.ticketId : undefined;
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const ticketPinned = usePinnedTicketsStore((state) =>
    ticketId === undefined ? false : state.pinnedAtById[ticketId] !== undefined,
  );

  return useMemo<SupportCommand[]>(() => {
    if (!supportEnabled) {
      return [];
    }

    const commands: SupportCommand[] = [
      {
        id: "support",
        label: "Support",
        keywords: "tickets queue conversations customer",
        icon: <LifebuoyIcon size={12} className="text-gray-11" />,
        action: "open-support",
        onRun: () => {
          closeSettingsDialog();
          navigateToSupport();
        },
      },
    ];

    for (const { scope, label } of SCOPE_COMMANDS) {
      commands.push({
        id: `support-scope-${scope}`,
        label,
        keywords: "tickets queue filter assigned",
        icon: <LifebuoyIcon size={12} className="text-gray-11" />,
        action: "support-set-scope",
        onRun: () => {
          closeSettingsDialog();
          const store = useSupportQueueStore.getState();
          store.setViewShortId(null);
          store.setAssigneeScope(scope);
          navigateToSupport();
        },
      });
    }

    if (!ticketId) {
      return commands;
    }

    const write = (
      updates: Parameters<typeof updateTicket.mutate>[0]["updates"],
    ) => updateTicket.mutate({ ticketId, updates });

    for (const { status, label } of STATUS_COMMANDS) {
      commands.push({
        id: `support-status-${status}`,
        label,
        keywords: "ticket status triage",
        icon:
          status === "resolved" ? (
            <CheckCircleIcon size={12} className="text-gray-11" />
          ) : (
            <LifebuoyIcon size={12} className="text-gray-11" />
          ),
        action: "support-set-status",
        onRun: () => write({ status }),
      });
    }

    for (const priority of Object.keys(
      TICKET_PRIORITY_LABELS,
    ) as Schemas.PriorityEnum[]) {
      commands.push({
        id: `support-priority-${priority}`,
        label: `Set priority to ${TICKET_PRIORITY_LABELS[priority].toLowerCase()}`,
        keywords: "ticket priority triage urgent",
        icon: <WarningCircleIcon size={12} className="text-gray-11" />,
        action: "support-set-priority",
        onRun: () => write({ priority }),
      });
    }

    if (currentUserId) {
      commands.push({
        id: "support-assign-me",
        label: "Assign ticket to me",
        keywords: "ticket assign take mine owner",
        icon: <UserIcon size={12} className="text-gray-11" />,
        action: "support-assign-ticket",
        onRun: () => write({ assignee: { type: "user", id: currentUserId } }),
      });
    }

    commands.push({
      id: "support-pin",
      label: ticketPinned ? "Unpin ticket" : "Pin ticket to My tickets",
      keywords: "ticket pin unpin favorite keep",
      icon: <PushPinIcon size={12} className="text-gray-11" />,
      action: "support-pin-ticket",
      onRun: () => usePinnedTicketsStore.getState().togglePinned(ticketId),
    });

    const cachedTicket = getCachedSupportTicket(ticketId);
    if (cachedTicket && isTicketSnoozed(cachedTicket, Date.now())) {
      commands.push({
        id: "support-wake",
        label: "Wake ticket from snooze",
        keywords: "ticket snooze wake unsnooze resume",
        icon: <ClockIcon size={12} className="text-gray-11" />,
        action: "support-wake-ticket",
        onRun: () => write({ snoozed_until: null }),
      });
    }

    commands.push({
      id: "support-snooze",
      label: "Snooze ticket for a day",
      keywords: "ticket snooze later hold",
      icon: <ClockIcon size={12} className="text-gray-11" />,
      action: "support-snooze-ticket",
      onRun: () =>
        write({
          snoozed_until: new Date(Date.now() + SNOOZE_MS).toISOString(),
        }),
    });

    commands.push({
      id: "support-reply",
      label: "Write a reply",
      keywords: "ticket respond customer message compose",
      icon: <ChatCircleIcon size={12} className="text-gray-11" />,
      action: "support-compose",
      onRun: () => {
        closeSettingsDialog();
        useSupportQueueStore.getState().setComposerMode("reply");
        useDraftStore.getState().actions.requestFocus(`ticket:${ticketId}`);
      },
    });

    commands.push({
      id: "support-note",
      label: "Write an internal note",
      keywords: "ticket private note team compose",
      icon: <NotePencilIcon size={12} className="text-gray-11" />,
      action: "support-compose",
      onRun: () => {
        closeSettingsDialog();
        useSupportQueueStore.getState().setComposerMode("note");
        useDraftStore.getState().actions.requestFocus(`ticket:${ticketId}`);
      },
    });

    if (projectId) {
      commands.push({
        id: "support-open-web",
        label: "Open ticket in PostHog web",
        keywords: "ticket browser web conversations",
        icon: <ArrowSquareOutIcon size={12} className="text-gray-11" />,
        action: "support-open-web",
        onRun: () => {
          const url = getPostHogUrl(
            `/project/${projectId}/support/tickets/${ticketId}`,
          );
          if (url) void openExternalUrl(url);
        },
      });
    }

    commands.push({
      id: "support-ask-agent",
      label: "Ask the agent about this ticket",
      keywords: "ticket agent ai investigate",
      icon: <RobotIcon size={12} className="text-gray-11" />,
      action: "support-ask-agent",
      onRun: () => {
        closeSettingsDialog();
        useSupportQueueStore.getState().setSidebarTab("agent");
      },
    });

    return commands;
  }, [
    supportEnabled,
    ticketId,
    ticketPinned,
    currentUserId,
    projectId,
    updateTicket,
    closeSettingsDialog,
  ]);
}
