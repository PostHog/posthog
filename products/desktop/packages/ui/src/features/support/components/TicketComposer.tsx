import { CaretDownIcon } from "@phosphor-icons/react";
import type { Schemas } from "@posthog/api-client";
import type { SupportTicket } from "@posthog/api-client/posthog-client";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { useReplyToSupportTicket } from "@posthog/ui/features/support/hooks/useReplyToSupportTicket";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import {
  type SupportComposerMode,
  useSupportQueueStore,
} from "@posthog/ui/features/support/supportQueueStore";
import { ticketStatusLabel } from "@posthog/ui/features/support/ticketPresentation";
import { useState } from "react";

const STATUSES_ON_SEND: Schemas.TicketStatusEnum[] = [
  "pending",
  "on_hold",
  "resolved",
];

export function TicketComposer({ ticket }: { ticket: SupportTicket }) {
  const mode = useSupportQueueStore((state) => state.composerMode);
  const { setComposerMode } = useSupportQueueStore.getState();

  const reply = useReplyToSupportTicket();
  const updateTicket = useUpdateSupportTicket();
  const isPrivate = mode === "note";
  const [statusOnSend, setStatusOnSend] =
    useState<Schemas.TicketStatusEnum | null>(null);

  const send = async (
    message: string,
    statusAfterSend?: Schemas.TicketStatusEnum,
  ) => {
    const content = message.trim();
    if (!content || reply.isPending) {
      return;
    }

    try {
      await reply.mutateAsync({
        ticketId: ticket.id,
        message: content,
        isPrivate,
      });
    } catch {
      return;
    }

    if (statusAfterSend) {
      updateTicket.mutate({
        ticketId: ticket.id,
        updates: { status: statusAfterSend },
      });
      setStatusOnSend(null);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col px-4 py-2">
      <PromptInput
        sessionId={`ticket:${ticket.id}`}
        placeholder={
          isPrivate
            ? "Write a note only your team can see…"
            : "Write a reply to the customer…"
        }
        hideDefaultToolbar
        enableFormatting
        editorHeight="fill"
        enableBashMode={false}
        clearOnSubmit
        isLoading={reply.isPending}
        submitDisabledExternal={reply.isPending}
        onSubmit={(text) => void send(text, statusOnSend ?? undefined)}
        messagingModeToggle={
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
        }
        toolbarEndSlot={
          isPrivate ? null : (
            <SendAndSetMenu
              disabled={reply.isPending}
              selected={statusOnSend}
              onPick={setStatusOnSend}
            />
          )
        }
      />
    </div>
  );
}

function SendAndSetMenu({
  disabled,
  selected,
  onPick,
}: {
  disabled: boolean;
  selected: Schemas.TicketStatusEnum | null;
  onPick: (status: Schemas.TicketStatusEnum | null) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="default" size="sm" disabled={disabled}>
            {selected ? `Then ${ticketStatusLabel(selected)}` : "Then…"}
            <CaretDownIcon size={10} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuItem onClick={() => onPick(null)}>
          Leave the status alone
        </DropdownMenuItem>
        {STATUSES_ON_SEND.map((status) => (
          <DropdownMenuItem key={status} onClick={() => onPick(status)}>
            {`Set to ${ticketStatusLabel(status).toLowerCase()}`}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
