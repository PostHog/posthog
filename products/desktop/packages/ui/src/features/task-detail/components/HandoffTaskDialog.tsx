import { CaretDown } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Checkbox,
  Combobox,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
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
import { ModalInlineComboboxContent } from "@posthog/ui/features/settings/ModalInlineComboboxContent";
import { useHandoffTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { useMemo, useRef, useState } from "react";
import { toast } from "../../../primitives/toast";
import { logger } from "../../../shell/logger";

const log = logger.scope("task-detail");

interface PersonItem {
  id: string;
  label: string;
  member: UserBasic;
}

/**
 * The confirm step of a handoff. The picker is a plain select anchored to the
 * dialog, the consequence copy reads as short GitHub-style sentences, and the
 * commit stays locked until a colleague is picked AND the acknowledge box is
 * checked. Only the recipient can reverse a handoff, so the menu item that
 * opens this carries an ellipsis.
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const anchorRef = useRef<HTMLDivElement>(null);

  const { members, isLoading: membersLoading } = useOrgMembers();
  const { channels } = useChannels();
  // A personal-space task moves into the recipient's personal space on handoff,
  // so the warning has to cover losing access, not just control.
  const movesToTheRecipient =
    !task.channel ||
    channels.find((channel) => channel.id === task.channel)?.channelType ===
      "personal";

  // Same reset rhythm as other dialogs: opening starts fresh. Adjusted during
  // render, not in an effect, because an effect would commit a frame of the
  // stale state first.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setSelectedId(null);
      setAcknowledged(false);
      setPickerOpen(false);
      setSearchQuery("");
    }
  }

  // ids as values — Base UI drops object items, and the selected label comes
  // straight from the item lookup.
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
  // Filtering is client-side over the org roster: name or email substring.
  const needle = searchQuery.trim().toLowerCase();
  const visibleItems = useMemo(
    () =>
      needle
        ? items.filter(
            (item) =>
              item.label.toLowerCase().includes(needle) ||
              (item.member.email ?? "").toLowerCase().includes(needle),
          )
        : items,
    [items, needle],
  );
  const itemIds = useMemo(
    () => visibleItems.map((item) => item.id),
    [visibleItems],
  );
  const selected = items.find((item) => item.id === selectedId);
  const canHandOff = selected !== undefined && acknowledged;

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
          <AlertDialogDescription render={<div />}>
            <p>
              <span className="font-medium text-foreground">{task.title}</span>{" "}
              goes to the person you pick.
            </p>
            <p>They steer it and get its notifications.</p>
            {movesToTheRecipient ? (
              <p>It moves into their personal space, so you lose access.</p>
            ) : null}
            <p>Only they can hand it back.</p>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3 px-4 pb-3">
          <div ref={anchorRef}>
            <Combobox
              items={itemIds}
              filter={null}
              value={selectedId}
              onValueChange={(value) => {
                setSelectedId(value as string | null);
                setPickerOpen(false);
                setSearchQuery("");
              }}
              open={pickerOpen}
              onOpenChange={(next) => {
                setPickerOpen(next);
                if (!next) setSearchQuery("");
              }}
              inputValue={searchQuery}
              onInputValueChange={(value) => setSearchQuery(value ?? "")}
              disabled={isPending}
              modal={false}
            >
              <ComboboxTrigger
                render={
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isPending}
                    aria-label="Pick a person to hand the task off to"
                    className="w-full justify-between"
                  >
                    {selected ? (
                      <span className="flex min-w-0 items-center gap-2">
                        <UserAvatar
                          user={selected.member}
                          size="xs"
                          className="shrink-0"
                        />
                        <span className="min-w-0 truncate">
                          {userDisplayName(selected.member)}
                        </span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">
                        Pick someone…
                      </span>
                    )}
                    <CaretDown
                      size={10}
                      weight="bold"
                      className="shrink-0 text-muted-foreground"
                    />
                  </Button>
                }
              />
              <ModalInlineComboboxContent
                anchor={anchorRef}
                side="bottom"
                sideOffset={4}
                className="w-[var(--anchor-width)] min-w-[240px]"
              >
                <ComboboxInput
                  placeholder="Search people…"
                  showTrigger={false}
                />
                <ComboboxEmpty>
                  {membersLoading ? "Loading people…" : "No people."}
                </ComboboxEmpty>
                <ComboboxList className="max-h-[min(18rem,calc(var(--available-height,18rem)-5rem))]">
                  {(itemId: string) => {
                    const item = visibleItems.find(
                      (entry) => entry.id === itemId,
                    );
                    if (!item) return null;
                    return (
                      <ComboboxItem key={item.id} value={item.id}>
                        <UserAvatar
                          user={item.member}
                          size="xs"
                          className="shrink-0"
                        />
                        <span className="min-w-0 truncate">{item.label}</span>
                        <span className="ml-auto shrink-0 truncate text-muted-foreground text-xs">
                          {item.member.email}
                        </span>
                      </ComboboxItem>
                    );
                  }}
                </ComboboxList>
              </ModalInlineComboboxContent>
            </Combobox>
          </div>
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
