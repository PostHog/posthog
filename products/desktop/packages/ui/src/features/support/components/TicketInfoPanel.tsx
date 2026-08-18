import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  PlusIcon,
  XIcon,
} from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import {
  githubIssueUrl,
  slackThreadUrl,
} from "@posthog/core/support/ticketLinks";
import { isTicketSnoozed } from "@posthog/core/support/ticketState";
import {
  isTicketTaskTag,
  readTicketTaskId,
} from "@posthog/core/support/ticketTaskLink";
import {
  Badge,
  Button,
  Chip,
  ChipClose,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Input,
  Text,
} from "@posthog/quill";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  TaskBadgeStack,
  TaskDotMark,
  TaskStatusTooltips,
} from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { useTaskStatusInput } from "@posthog/ui/features/sidebar/useTaskStatusInput";
import {
  Row,
  Section,
} from "@posthog/ui/features/support/components/SidebarSection";
import { TicketActivity } from "@posthog/ui/features/support/components/TicketActivity";
import { TicketHistory } from "@posthog/ui/features/support/components/TicketHistory";
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
import { type ReactNode, useState } from "react";

const STATUS_OPTIONS = Object.keys(
  TICKET_STATUS_LABELS,
) as Schemas.TicketStatusEnum[];
const PRIORITY_OPTIONS = Object.keys(
  TICKET_PRIORITY_LABELS,
) as Schemas.PriorityEnum[];

export function TicketInfoPanel({ ticket }: { ticket: SupportTicket }) {
  const updateTicket = useUpdateSupportTicket();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const currentUserId = currentUser?.id;
  const assignedToMe =
    currentUserId !== undefined &&
    ticket.assignee?.type === "user" &&
    String(ticket.assignee.id) === String(currentUserId);
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
          <PickerMenu
            trigger={
              <Text className="text-[12px]">{ticketAssigneeName(ticket)}</Text>
            }
            value={assignedToMe ? "me" : ticket.assignee ? "other" : "none"}
            options={[
              ...(currentUserId ? [{ value: "me", label: "Me" }] : []),
              { value: "none", label: "Unassigned" },
            ]}
            onSelect={(value) =>
              write({
                assignee:
                  value === "me" && currentUserId
                    ? { type: "user", id: currentUserId }
                    : null,
              })
            }
          />
        </Row>

        <Row label="Snooze">
          {snoozed ? (
            <div className="flex items-center gap-2">
              <Text className="text-[12px] text-muted-foreground">
                {formatSnoozedUntil(ticket.snoozed_until)}
              </Text>
              <Button
                variant="default"
                size="sm"
                onClick={() => write({ snoozed_until: null })}
              >
                Wake now
              </Button>
            </div>
          ) : (
            <Text className="text-[12px] text-muted-foreground">
              Not snoozed
            </Text>
          )}
        </Row>

        <TicketAgentRow taskId={readTicketTaskId(ticket.tags)} />

        <Row label="Tags">
          <TicketTags
            tags={labelTags}
            onChange={(next) =>
              write({
                tags: [...(ticket.tags ?? []).filter(isTicketTaskTag), ...next],
              })
            }
          />
        </Row>
      </Section>

      <Section title="Requester">
        <Row label="Name">
          <Text className="font-medium text-[12px]">
            {ticketRequesterName(ticket)}
          </Text>
        </Row>
        <Row label="Channel">
          <ChannelValue ticket={ticket} />
        </Row>
      </Section>

      <TicketActivity ticketId={ticket.id} />
      <TicketHistory ticket={ticket} />
    </div>
  );
}

function TicketTags({
  tags,
  onChange,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  const commit = () => {
    const tag = draft.trim();
    if (tag && !tags.includes(tag)) {
      onChange([...tags, tag]);
    }
    setDraft("");
    setAdding(false);
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-1">
      {tags.map((tag) => (
        <Chip key={tag}>
          <span className="max-w-40 truncate">{tag}</span>
          <ChipClose
            aria-label={`Remove ${tag}`}
            onClick={() => onChange(tags.filter((t) => t !== tag))}
          >
            <XIcon size={12} weight="bold" />
          </ChipClose>
        </Chip>
      ))}

      {adding ? (
        <Input
          autoFocus
          value={draft}
          placeholder="Tag name"
          className="h-6 w-32 text-[12px]"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit();
            }
            if (event.key === "Escape") {
              setDraft("");
              setAdding(false);
            }
          }}
        />
      ) : (
        <Button
          variant="outline"
          size="sm"
          aria-label="Add tag"
          onClick={() => setAdding(true)}
        >
          <PlusIcon size={11} weight="bold" />
          {tags.length === 0 ? "Add tag" : null}
        </Button>
      )}
    </div>
  );
}

function ChannelValue({ ticket }: { ticket: SupportTicket }) {
  const slackUrl = slackThreadUrl(ticket);
  const issueUrl = githubIssueUrl(ticket);

  return (
    <div className="flex items-center gap-2">
      <Text className="font-medium text-[12px]">{ticket.channel_source}</Text>
      {slackUrl && <ExternalRowLink href={slackUrl} label="Open in Slack" />}
      {issueUrl && (
        <ExternalRowLink
          href={issueUrl}
          label={`#${ticket.github_issue_number}`}
        />
      )}
    </div>
  );
}

function ExternalRowLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="flex items-center gap-0.5 text-[12px] text-accent hover:underline"
    >
      {label}
      <ArrowSquareOutIcon size={11} />
    </a>
  );
}

function formatSnoozedUntil(snoozedUntil: string | null | undefined): string {
  if (!snoozedUntil) {
    return "";
  }
  const until = Date.parse(snoozedUntil);
  return Number.isNaN(until) ? "" : `until ${new Date(until).toLocaleString()}`;
}

function TicketAgentRow({ taskId }: { taskId: string | null }) {
  const { data: task } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
  });
  const status = useTaskStatusInput(task);

  if (!status) {
    return null;
  }

  const dot = taskDot(status);

  return (
    <Row label="Agent">
      <TaskStatusTooltips>
        <div className="flex min-w-0 items-center gap-1.5">
          <TaskDotMark dot={dot} />
          <Text className="truncate text-[12px]">{dot.label}</Text>
          <TaskBadgeStack status={status} />
        </div>
      </TaskStatusTooltips>
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
