import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { Button, buttonGroupVariants, cn } from "@posthog/quill";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { ReactNode } from "react";

/**
 * A file, wherever it is named: in a message, on an activity row. Opens in an
 * artifact tab, with a joined half for saving it to disk.
 *
 * Presentation only, so both surfaces can hand it their own handlers - and so
 * a file reads the same in both places.
 */
export function ArtifactChip({
  label,
  name,
  meta,
  onOpen,
  onDownload,
  downloading,
  disabled,
}: {
  label: ReactNode;
  name?: string;
  /** Trailing muted detail: a size in a message, a version on an activity row. */
  meta?: ReactNode;
  onOpen?: () => void;
  onDownload?: () => void;
  downloading?: boolean;
  disabled?: boolean;
}) {
  return (
    // quill's ButtonGroup is a div, and this renders inside a message's
    // paragraph, so the group's own contract is spelled out on a span instead.
    // The halves stay siblings for the same reason: no button within a button.
    // biome-ignore lint/a11y/useSemanticElements: <fieldset> is block-level and this sits in a paragraph
    <span
      role="group"
      data-quill
      data-slot="button-group"
      data-orientation="horizontal"
      className={cn(
        buttonGroupVariants(),
        "mx-0.5 inline-block max-w-full whitespace-nowrap align-middle",
      )}
    >
      <Button
        onClick={onOpen}
        disabled={disabled || !onOpen}
        aria-label={name ? `Open ${name}` : undefined}
        className={cn(
          "inline-block select-text truncate align-top leading-[1.375rem]",
          onDownload ? "max-w-[calc(100%-1.5rem)]" : "max-w-full",
        )}
        variant="outline"
        size="sm"
      >
        {typeof name === "string" && (
          <span className="mr-1 inline-block align-[-0.125em]">
            <FileIcon filename={name} size={12} />
          </span>
        )}
        {label}
        {meta && <span className="text-muted-foreground"> {meta}</span>}
      </Button>
      {onDownload && (
        <Tooltip content={downloading ? "Downloading…" : "Download"}>
          <Button
            size="icon-sm"
            variant="outline"
            onClick={onDownload}
            disabled={downloading}
            aria-label={name ? `Download ${name}` : "Download"}
            className="align-top"
          >
            <DownloadSimpleIcon size={12} />
          </Button>
        </Tooltip>
      )}
    </span>
  );
}
