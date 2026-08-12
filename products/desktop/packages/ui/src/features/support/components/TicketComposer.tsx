import { ArrowUpIcon, CaretDownIcon } from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  InputGroup,
  InputGroupTextarea,
  Text,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { useReplyToSupportTicket } from "@posthog/ui/features/support/hooks/useReplyToSupportTicket";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import {
  type SupportComposerMode,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { ticketStatusLabel } from "@posthog/ui/features/support/ticketPresentation";
import { useState } from "react";

/** Statuses worth setting straight off the back of a reply. */
const STATUSES_ON_SEND: Schemas.TicketStatusEnum[] = [
  "pending",
  "on_hold",
  "resolved",
];

export function TicketComposer({ ticket }: { ticket: SupportTicket }) {
  const mode = useSupportQueueStore((state) => state.composerMode);
  const { setComposerMode } = useSupportQueueStore.getState();
  const [draft, setDraft] = useState("");

  const reply = useReplyToSupportTicket();
  const updateTicket = useUpdateSupportTicket();

  const isPrivate = mode === "note";
  const canSend = draft.trim().length > 0 && !reply.isPending;

  const send = async (statusAfterSend?: Schemas.TicketStatusEnum) => {
    if (!canSend) {
      return;
    }

    try {
      await reply.mutateAsync({
        ticketId: ticket.id,
        message: draft.trim(),
        isPrivate,
      });
    } catch {
      // The hook has already explained the outcome; the draft stays put so it
      // can be sent again once the person has checked the thread.
      return;
    }

    setDraft("");

    if (statusAfterSend) {
      updateTicket.mutate({
        idOrNumber: ticket.id,
        updates: { status: statusAfterSend },
      });
    }
  };

  return (
    <div className="flex shrink-0 flex-col gap-1 border-border border-t px-4 py-2">
      <InputGroup className="h-auto bg-card">
        <InputGroupTextarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            isPrivate
              ? "Write a note only your team can see…"
              : "Write a reply to the customer…"
          }
          className="min-h-[64px] text-[13px]"
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void send();
            }
          }}
        />
      </InputGroup>

      <div className="flex items-center gap-1">
        <ToggleGroup
          value={[mode]}
          onValueChange={(value) => {
            const next = value[0] as SupportComposerMode | undefined;
            if (next) {
              setComposerMode(next);
            }
          }}
        >
          <ToggleGroupItem value="reply" size="sm">
            Reply
          </ToggleGroupItem>
          <ToggleGroupItem value="note" size="sm">
            Internal note
          </ToggleGroupItem>
        </ToggleGroup>

        <Text className="ml-2 text-[11px] text-muted-foreground">
          {isPrivate
            ? "Never sent to the customer"
            : `Sends over ${ticket.channel_source}`}
        </Text>

        <div className="ml-auto flex items-center gap-1">
          {!isPrivate && (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button variant="default" size="sm" disabled={!canSend}>
                    Send and set
                    <CaretDownIcon size={10} weight="bold" />
                  </Button>
                }
              />
              <DropdownMenuContent align="end">
                {STATUSES_ON_SEND.map((status) => (
                  <DropdownMenuItem
                    key={status}
                    onClick={() => void send(status)}
                  >
                    {ticketStatusLabel(status)}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          <Button
            variant="primary"
            size="sm"
            disabled={!canSend}
            data-loading={reply.isPending || undefined}
            onClick={() => void send()}
          >
            {isPrivate ? "Add note" : "Send"}
            <ArrowUpIcon size={12} weight="bold" />
          </Button>
        </div>
      </div>
    </div>
  );
}
