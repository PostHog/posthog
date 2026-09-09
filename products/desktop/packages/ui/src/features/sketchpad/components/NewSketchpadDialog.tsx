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
} from "@posthog/quill";
import {
  DEFAULT_SKETCHPAD_NAME,
  DIALOG_CANCEL,
} from "@posthog/ui/features/sketchpad/sketchpadCopy";
import { type ReactElement, useEffect, useState } from "react";

export type SketchpadNameDialogMode = "create" | "rename";

interface NewSketchpadDialogProps {
  open: boolean;
  mode?: SketchpadNameDialogMode;
  initialName?: string;
  isPending: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string) => void;
}

const COPY: Record<
  SketchpadNameDialogMode,
  { title: string; description: string; submit: string }
> = {
  create: {
    title: "New sketchpad",
    description: "Give the sketchpad a name. You can change it later.",
    submit: "Create sketchpad",
  },
  rename: {
    title: "Rename sketchpad",
    description: "The new name is shown to everyone on the sketchpad.",
    submit: "Save name",
  },
};

export function NewSketchpadDialog({
  open,
  mode = "create",
  initialName = "",
  isPending,
  onOpenChange,
  onSubmit,
}: NewSketchpadDialogProps): ReactElement {
  const [name, setName] = useState(initialName);
  const copy = COPY[mode];
  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && !isPending;

  useEffect(() => {
    if (!open) return;
    setName(initialName || (mode === "create" ? DEFAULT_SKETCHPAD_NAME : ""));
  }, [open, initialName, mode]);

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(trimmed);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Field className="gap-1.5">
            <FieldLabel htmlFor="sketchpad-board-name">Name</FieldLabel>
            <Input
              id="sketchpad-board-name"
              autoFocus
              value={name}
              placeholder="Weekly metrics"
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing || event.keyCode === 229)
                  return;
                if (event.key === "Enter") submit();
              }}
            />
          </Field>
        </DialogBody>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            {DIALOG_CANCEL}
          </Button>
          <Button
            variant="primary"
            loading={isPending}
            disabled={!canSubmit}
            onClick={submit}
          >
            {copy.submit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
