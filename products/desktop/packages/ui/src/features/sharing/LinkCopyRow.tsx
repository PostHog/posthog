import { Button, Input, Label, Text } from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import { useId } from "react";

/**
 * A labeled, read-only link with a copy button. `url` is null when the app
 * cannot build a link yet (no signed-in region), in which case the row says so
 * instead of offering an empty field.
 */
export function LinkCopyRow({
  label,
  description,
  url,
  copiedDescription,
  onCopied,
  dataAttr,
}: {
  label: string;
  description?: string;
  url: string | null;
  /** The toast's second line, saying what the copied link does. */
  copiedDescription: string;
  onCopied?: (success: boolean) => void;
  dataAttr: string;
}) {
  const inputId = useId();

  const copy = async (): Promise<void> => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link copied", { description: copiedDescription });
      onCopied?.(true);
    } catch (error) {
      toast.error("Couldn't copy link", {
        description: error instanceof Error ? error.message : String(error),
      });
      onCopied?.(false);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      {description ? (
        <Text size="xs" variant="muted">
          {description}
        </Text>
      ) : null}
      {url ? (
        <div className="flex items-center gap-2">
          <Input
            id={inputId}
            readOnly
            value={url}
            className="min-w-0 flex-1 font-mono text-xs"
            onFocus={(event) => event.currentTarget.select()}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => void copy()}
            data-attr={dataAttr}
          >
            Copy
          </Button>
        </div>
      ) : (
        <Text size="xs" variant="muted">
          Couldn't build this link. Sign in again and reopen the dialog.
        </Text>
      )}
    </div>
  );
}
