import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Autocomplete,
  AutocompleteCollection,
  AutocompleteEmpty,
  AutocompleteGroup,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
  Button,
  Checkbox,
  DialogBody,
  Field,
  FieldLabel,
} from "@posthog/quill";
import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useHandoffTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useMemo, useState } from "react";
import { toast } from "../../../primitives/toast";
import { logger } from "../../../shell/logger";

const log = logger.scope("task-detail");

interface PersonItem {
  id: string;
  label: string;
  member: UserBasic;
}

/**
 * The confirm step of a handoff. The same shape as the canvas delete confirm:
 * a short title, two sentences of consequence, the person picker (search input
 * over the same avatar rows the mention composer draws), then Cancel against
 * the commit. Only the recipient can reverse a handoff, so the item that opens
 * this carries an ellipsis.
 */
export function HandoffTaskDialog({
  task,
  open,
  onOpenChange,
}: {
  task: Task;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const currentUser = useCurrentUser();
  const { mutate: handoffTask, isPending } = useHandoffTask();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const { members, isLoading: membersLoading } = useOrgMembers();
  const { channels } = useChannels();
  // A personal-space task moves into the recipient's personal space on handoff,
  // so the warning has to cover losing access, not just control.
  const movesToTheRecipient =
    !task.channel ||
    channels.find((channel) => channel.id === task.channel)?.channelType ===
      "personal";

  // Same reset rhythm as other dialogs: opening starts a clean search and no
  // selection. Adjusted during render, not in an effect, because an effect
  // would commit a frame of the stale state first.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setQuery("");
      setSelectedId(null);
      setAcknowledged(false);
    }
  }

  const items = useMemo<PersonItem[]>(
    () =>
      members.flatMap((member) =>
        member.id === currentUser.data?.id
          ? []
          : [
              {
                id: String(member.id),
                label: userDisplayName(member),
                member,
              },
            ],
      ),
    [members, currentUser.data?.id],
  );
  const selected = items.find((item) => item.id === selectedId);

  const handleConfirm = () => {
    if (!selected) return;
    const name = userDisplayName(selected.member);
    handoffTask(
      { taskId: task.id, userId: selected.member.id },
      {
        onSuccess: () => {
          toast.success(`Handed "${task.title}" off to ${name}`);
          onOpenChange(false);
        },
        onError: (error) => {
          log.error("Failed to hand off task", error);
          toast.error("Couldn't hand off the task. Try again.");
        },
      },
    );
  };

  const canHandOff = selected !== undefined && acknowledged;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        // Hold the dialog while the request is in flight; closing mid-flight
        // would look like a cancel while the handoff still goes through.
        if (!next && isPending) return;
        onOpenChange(next);
      }}
    >
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Hand off task</AlertDialogTitle>
          <AlertDialogDescription>
            <span className="font-medium text-foreground">{task.title}</span>{" "}
            goes to the person you pick:
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3 px-4 pb-3">
          <ul className="list-disc space-y-1 pl-4 text-muted-foreground text-xs">
            <li>They steer it and get its notifications.</li>
            {movesToTheRecipient ? (
              <li>It moves into their personal space, so you lose access.</li>
            ) : null}
            <li>Only they can hand it back.</li>
          </ul>
          <Autocomplete<PersonItem>
            inline
            defaultOpen
            items={[{ items }]}
            value={query}
            autoHighlight="always"
            onValueChange={(value, eventDetails) => {
              if (eventDetails.reason !== "input-change") return;
              if (typeof value === "string") setQuery(value);
            }}
            filter={(item, search) => {
              if (!search) return true;
              const needle = search.toLowerCase();
              return (
                item.label.toLowerCase().includes(needle) ||
                (item.member.email ?? "").toLowerCase().includes(needle)
              );
            }}
          >
            <AutocompleteInput
              placeholder="Search people…"
              autoFocus
              showClear
              disabled={isPending}
            />
            <AutocompleteEmpty>
              <span>{membersLoading ? "Loading people…" : "No people."}</span>
            </AutocompleteEmpty>
            <AutocompleteList className="h-44 p-0">
              {(section: { items: PersonItem[] }) => (
                <AutocompleteGroup items={section.items} className="p-0">
                  <AutocompleteCollection>
                    {(item: PersonItem) => (
                      <AutocompleteItem
                        key={item.id}
                        value={item.id}
                        data-selected={selectedId === item.id || undefined}
                        onClick={() => setSelectedId(item.id)}
                        // Same fill-on-select and softened focus ring as the
                        // channels sidebar rows; the span override lets the
                        // email reach the row's right edge under quill's own
                        // child wrapper.
                        className="w-full min-w-0 ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-selected:bg-fill-selected data-selected:text-foreground data-highlighted:ring-0 [&>span]:w-full [&>span]:gap-2"
                      >
                        <UserAvatar
                          user={item.member}
                          size="xs"
                          className="shrink-0"
                        />
                        <span className="truncate font-medium text-xs">
                          {item.label}
                        </span>
                        <span className="ml-auto shrink-0 truncate text-muted-foreground text-xs">
                          {item.member.email}
                        </span>
                      </AutocompleteItem>
                    )}
                  </AutocompleteCollection>
                </AutocompleteGroup>
              )}
            </AutocompleteList>
          </Autocomplete>
          <Field orientation="horizontal" className="items-center gap-2">
            <Checkbox
              id="handoff-acknowledge"
              checked={acknowledged}
              onCheckedChange={(checked) => setAcknowledged(checked === true)}
              disabled={isPending}
            />
            <FieldLabel htmlFor="handoff-acknowledge" className="font-normal">
              I understand I can&apos;t undo this myself.
            </FieldLabel>
          </Field>
        </DialogBody>
        <AlertDialogFooter>
          <AlertDialogClose
            render={
              <Button variant="outline" size="sm" disabled={isPending}>
                Cancel
              </Button>
            }
          />
          <Button
            variant="primary"
            size="sm"
            disabled={!canHandOff}
            loading={isPending}
            onClick={handleConfirm}
          >
            Hand off
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
