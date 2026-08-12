import { CaretDownIcon } from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { isTicketSnoozed } from "@posthog/core/support/ticketState";
import {
  isTicketTaskTag,
  readTicketTaskId,
} from "@posthog/core/support/ticketTaskLink";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Text,
} from "@posthog/quill";
import { readPrUrls } from "@posthog/shared";
import { PRBadgeLink } from "@posthog/ui/features/git-interaction/components/PRBadgeLink";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import {
  TICKET_PRIORITY_LABELS,
  TICKET_PRIORITY_VARIANTS,
  TICKET_STATUS_LABELS,
  TICKET_STATUS_VARIANTS,
  ticketAssigneeName,
  ticketPriorityLabel,
  ticketRequesterName,
  ticketStatusLabel,
} from "@posthog/ui/features/support/ticketPresentation";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

const STATUS_OPTIONS = Object.keys(
  TICKET_STATUS_LABELS,
) as Schemas.TicketStatusEnum[];
const PRIORITY_OPTIONS = Object.keys(
  TICKET_PRIORITY_LABELS,
) as Schemas.PriorityEnum[];

export function TicketInfoPanel({ ticket }: { ticket: SupportTicket }) {
  const updateTicket = useUpdateSupportTicket();
  const snoozed = isTicketSnoozed(ticket, Date.now());
  const labelTags = (ticket.tags ?? []).filter((tag) => !isTicketTaskTag(tag));

  const write = (
    updates: Parameters<typeof updateTicket.mutate>[0]["updates"],
  ) => updateTicket.mutate({ ticketId: ticket.id, updates });

  return (
    <div className="flex flex-col gap-4 p-3">
      <Section title="Ticket">
        <Row label="Status">
          <PickerMenu
            trigger={
              <Badge variant={TICKET_STATUS_VARIANTS[ticket.status ?? "new"]}>
                {ticketStatusLabel(ticket.status)}
              </Badge>
            }
            value={ticket.status ?? "new"}
            options={STATUS_OPTIONS.map((status) => ({
              value: status,
              label: TICKET_STATUS_LABELS[status],
            }))}
            onSelect={(value) =>
              write({ status: value as Schemas.TicketStatusEnum })
            }
          />
        </Row>

        <Row label="Priority">
          <PickerMenu
            trigger={
              ticket.priority ? (
                <Badge variant={TICKET_PRIORITY_VARIANTS[ticket.priority]}>
                  {ticketPriorityLabel(ticket.priority)}
                </Badge>
              ) : (
                <Text className="text-[12px] text-muted-foreground">
                  No priority
                </Text>
              )
            }
            value={ticket.priority ?? "none"}
            options={[
              { value: "none", label: "No priority" },
              ...PRIORITY_OPTIONS.map((priority) => ({
                value: priority,
                label: TICKET_PRIORITY_LABELS[priority],
              })),
            ]}
            onSelect={(value) =>
              write({
                priority:
                  value === "none" ? null : (value as Schemas.PriorityEnum),
              })
            }
          />
        </Row>

        <Row label="Assignee">
          <Text className="font-medium text-[12px]">
            {ticketAssigneeName(ticket)}
          </Text>
        </Row>

        <Row label="Snooze">
          {snoozed ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => write({ snoozed_until: null })}
            >
              Wake now
            </Button>
          ) : (
            <Text className="text-[12px] text-muted-foreground">
              Not snoozed
            </Text>
          )}
        </Row>

        <TicketPullRequestRow taskId={readTicketTaskId(ticket.tags)} />

        {labelTags.length > 0 && (
          <Row label="Tags">
            <div className="flex flex-wrap justify-end gap-1">
              {labelTags.map((tag) => (
                <Badge key={tag} variant="default">
                  {tag}
                </Badge>
              ))}
            </div>
          </Row>
        )}
      </Section>

      <Section title="Requester">
        <Row label="Name">
          <Text className="font-medium text-[12px]">
            {ticketRequesterName(ticket)}
          </Text>
        </Row>
        <Row label="Channel">
          <Text className="font-medium text-[12px]">
            {ticket.channel_source}
          </Text>
        </Row>
        <Row label="Messages">
          <Text className="font-medium text-[12px] tabular-nums">
            {ticket.message_count}
          </Text>
        </Row>
      </Section>
    </div>
  );
}

function TicketPullRequestRow({ taskId }: { taskId: string | null }) {
  const { data: task } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
  });
  const prUrl = readPrUrls(task?.latest_run?.output)[0];
  const { prState } = useTaskPrStatus({
    id: task?.id ?? "",
    cloudPrUrl: prUrl ?? null,
    taskRunEnvironment: task?.latest_run?.environment ?? null,
  });

  if (!prUrl) {
    return null;
  }

  return (
    <Row label="Pull request">
      <PRBadgeLink
        prUrl={prUrl}
        prState={prState === "closed" ? "closed" : "open"}
        merged={prState === "merged"}
        draft={prState === "draft"}
        compact
      />
    </Row>
  );
}

function PickerMenu({
  trigger,
  value,
  options,
  onSelect,
}: {
  trigger: ReactNode;
  value: string;
  options: Array<{ value: string; label: string }>;
  onSelect: (value: string) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="default" size="sm">
            {trigger}
            <CaretDownIcon size={10} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={value} onValueChange={onSelect}>
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Text className="px-0.5 font-semibold text-[10px] text-muted-foreground uppercase tracking-wider">
        {title}
      </Text>
      <div className="rounded-(--radius-3) border border-border bg-card px-2.5">
        {children}
      </div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-8 items-center justify-between gap-2 border-border border-b py-1 last:border-b-0">
      <Text className="text-[12px] text-muted-foreground">{label}</Text>
      {children}
    </div>
  );
}
