import { PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useEffect, useMemo, useState } from "react";

function isValidFileName(name: string): boolean {
  const hasControlCharacter = [...name].some((character) => {
    const code = character.charCodeAt(0);
    return code <= 31 || code === 127;
  });
  return (
    name.endsWith(".md") &&
    name.length <= 128 &&
    !hasControlCharacter &&
    !name.includes("/") &&
    !name.includes("\\") &&
    name !== ".md"
  );
}

export function NewSpaceFileDialog({
  channels,
  open,
  isCreating,
  onOpenChange,
  onCreate,
}: {
  channels: Channel[];
  open: boolean;
  isCreating: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (input: { channelId: string; name: string }) => Promise<void>;
}) {
  const [channelId, setChannelId] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const channelOptions = useMemo(
    () =>
      channels.map((channel) => ({ value: channel.id, label: channel.name })),
    [channels],
  );

  useEffect(() => {
    if (open) {
      setChannelId(channels[0]?.id ?? "");
      setName("");
      setError(null);
    }
  }, [channels, open]);

  const submit = async (): Promise<void> => {
    if (isCreating || !channelId || !isValidFileName(name)) return;
    setError(null);
    try {
      await onCreate({ channelId, name });
      onOpenChange(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Couldn't create file.",
      );
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !isCreating && onOpenChange(next)}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New file</DialogTitle>
          <DialogDescription>
            Choose a space and a Markdown file name.
          </DialogDescription>
        </DialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3">
          <Field>
            <FieldLabel htmlFor="space-file-space">Space</FieldLabel>
            <Select
              value={channelId}
              onValueChange={(value) => setChannelId(value ?? "")}
              items={channelOptions}
            >
              <SelectTrigger
                id="space-file-space"
                aria-label="Space"
                className="w-full"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {channelOptions.map((channel) => (
                  <SelectItem key={channel.value} value={channel.value}>
                    {channel.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="space-file-name">File name</FieldLabel>
            <Input
              id="space-file-name"
              value={name}
              placeholder="notes.md"
              disabled={isCreating}
              onChange={(event) => setName(event.target.value)}
            />
            {!isValidFileName(name) && name !== "" && (
              <span className="text-destructive text-xs">
                Use a flat file name ending in .md.
              </span>
            )}
          </Field>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={isCreating}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={isCreating}
            disabled={!channelId || !isValidFileName(name)}
            data-attr="create-space-file"
            onClick={() => void submit()}
          >
            <PlusIcon size={14} />
            Create file
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
