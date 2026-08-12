import {
  CheckCircleIcon,
  ClockIcon,
  LifebuoyIcon,
  RobotIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { CommandMenuAction } from "@posthog/shared/analytics-events";
import { useSupportFlag } from "@posthog/ui/features/feature-flags/useSupportFlag";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import { useSupportQueueStore } from "@posthog/ui/features/support/supportQueueStore";
import { TICKET_PRIORITY_LABELS } from "@posthog/ui/features/support/ticketPresentation";
import { navigateToSupport } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
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

  const ticketId = view.type === "support" ? view.ticketId : undefined;

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
  }, [supportEnabled, ticketId, updateTicket, closeSettingsDialog]);
}
