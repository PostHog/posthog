import { CaretDownIcon } from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import {
  resolveTicketPrUrls,
  ticketPrUrlFromTag,
} from "@posthog/core/support/ticketPrLinks";
import { isTicketSnoozed } from "@posthog/core/support/ticketState";
import { readTicketTaskId } from "@posthog/core/support/ticketTaskLink";
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
import { TicketPullRequests } from "@posthog/ui/features/support/components/TicketPullRequests";
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

  // The thread's task, for the pull requests it opened and their state. The
  // query is shared with the agent panel, so this costs no extra request.
  const taskId = readTicketTaskId(ticket.tags);
  const { data: task } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
  });
  const prUrls = resolveTicketPrUrls(
    ticket.tags,
    readPrUrls(task?.latest_run?.output),
  );
  // The link tags render as their own rows above, so showing them again here
  // would present plumbing as something someone chose to label the ticket with.
  const labelTags = (ticket.tags ?? []).filter(
    (tag) =>
      !ticketPrUrlFromTag(tag) && !tag.toLowerCase().startsWith("ai-task:"),
  );

  const write = (
    updates: Parameters<typeof updateTicket.mutate>[0]["updates"],
  ) => updateTicket.mutate({ idOrNumber: ticket.id, updates });

  return (
    <div className="flex flex-col gap-4 p-3">
      <Section title="Ticket">
        <Row label="Status">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="default" size="sm">
                  <Badge
                    variant={TICKET_STATUS_VARIANTS[ticket.status ?? "new"]}
                  >
                    {ticketStatusLabel(ticket.status)}
                  </Badge>
                  <CaretDownIcon size={10} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              <DropdownMenuRadioGroup
                value={ticket.status ?? "new"}
                onValueChange={(value) =>
                  write({ status: value as Schemas.TicketStatusEnum })
                }
              >
                {STATUS_OPTIONS.map((status) => (
                  <DropdownMenuRadioItem key={status} value={status}>
                    {TICKET_STATUS_LABELS[status]}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </Row>

        <Row label="Priority">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="default" size="sm">
                  {ticket.priority ? (
                    <Badge variant={TICKET_PRIORITY_VARIANTS[ticket.priority]}>
                      {ticketPriorityLabel(ticket.priority)}
                    </Badge>
                  ) : (
                    <Text className="text-[12px] text-muted-foreground">
                      No priority
                    </Text>
                  )}
                  <CaretDownIcon size={10} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              <DropdownMenuRadioGroup
                value={ticket.priority ?? "none"}
                onValueChange={(value) =>
                  write({
                    priority:
                      value === "none" ? null : (value as Schemas.PriorityEnum),
                  })
                }
              >
                <DropdownMenuRadioItem value="none">
                  No priority
                </DropdownMenuRadioItem>
                {PRIORITY_OPTIONS.map((priority) => (
                  <DropdownMenuRadioItem key={priority} value={priority}>
                    {TICKET_PRIORITY_LABELS[priority]}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
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

        <Row label={prUrls.length > 1 ? "Pull requests" : "Pull request"}>
          <TicketPullRequests prUrls={prUrls} task={task} />
        </Row>

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
        {ticket.email_from && (
          <Row label="Email">
            <Text className="truncate font-medium text-[12px]">
              {ticket.email_from}
            </Text>
          </Row>
        )}
        <Row label="Messages">
          <Text className="font-medium text-[12px] tabular-nums">
            {ticket.message_count}
          </Text>
        </Row>
      </Section>
    </div>
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
