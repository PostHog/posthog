import { Button, Input, Label, Text } from "@posthog/quill";
import { useId } from "react";
import { copyLinkToClipboard } from "./copyLink";

/**
 * A read-only link with a copy button. `url` is null when the app cannot build
 * a link yet (no signed-in region), in which case the row says so instead of
 * offering an empty field.
 */
export function LinkCopyRow({
  label,
  hideLabel = false,
  url,
  copiedDescription,
  onCopied,
  dataAttr,
}: {
  /** Names the field for assistive tech; shown above it unless `hideLabel`. */
  label: string;
  hideLabel?: boolean;
  url: string | null;
  /** The toast's second line, saying what the copied link does. */
  copiedDescription: string;
  onCopied?: (success: boolean) => void;
  dataAttr: string;
}) {
  const inputId = useId();

  if (!url) {
    return (
      <Text size="xs" variant="muted">
        Couldn't build this link. Sign in again and reopen the dialog.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {hideLabel ? null : <Label htmlFor={inputId}>{label}</Label>}
      <div className="flex items-center gap-2">
        <Input
          id={inputId}
          readOnly
          value={url}
          aria-label={hideLabel ? label : undefined}
          className="min-w-0 flex-1 font-mono text-xs"
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button
          variant="outline"
          onClick={() =>
            void copyLinkToClipboard(url, copiedDescription, onCopied)
          }
          data-attr={dataAttr}
        >
          Copy
        </Button>
      </div>
    </div>
  );
}
