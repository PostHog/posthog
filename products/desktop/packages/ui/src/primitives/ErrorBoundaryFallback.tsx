import { ArrowClockwise, Check, Copy } from "@phosphor-icons/react";
import {
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Heading,
  Text,
} from "@posthog/quill";
import { warningHog } from "@posthog/ui/assets/hedgehogs";
import {
  buildErrorReport,
  summarizeError,
} from "@posthog/ui/primitives/errorReport";
import { useEffect, useRef, useState } from "react";

/** How long the copy button confirms before it returns to its resting label. */
const COPIED_MS = 2000;

export interface ErrorBoundaryFallbackProps {
  error: Error;
  componentStack?: string | null;
  /** The `name` of the boundary that caught the error, included in the copied report. */
  boundaryName?: string;
  onRefresh: () => void;
}

/**
 * The screen an `ErrorBoundary` shows in place of a crashed subtree. Pure:
 * everything it renders comes from props, so the story and the boundary share
 * one implementation.
 */
export function ErrorBoundaryFallback({
  error,
  componentStack,
  boundaryName,
  onRefresh,
}: ErrorBoundaryFallbackProps) {
  const [copied, setCopied] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => (timer.current ? clearTimeout(timer.current) : undefined),
    [],
  );

  const report = buildErrorReport({
    error,
    componentStack,
    boundaryName,
    timestamp: new Date(),
    userAgent:
      typeof navigator !== "undefined" ? navigator.userAgent : undefined,
  });

  async function copyReport() {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      // Clipboard access can be denied, so the details panel stays selectable as the fallback.
    }
  }

  const summary = summarizeError(error);

  return (
    <div
      role="alert"
      className="@container flex h-full min-h-64 w-full flex-1 justify-center overflow-y-auto p-6"
    >
      <div className="my-auto flex w-full max-w-md flex-col items-center gap-6 text-center">
        <img
          src={warningHog}
          alt=""
          className="pointer-events-none @max-[420px]:w-28 w-36 select-none"
        />
        <div className="flex w-full flex-col items-center gap-2">
          <Heading size="lg">Something went wrong</Heading>
          <Text size="sm" variant="muted" className="text-balance">
            PostHog hit an error it could not recover from. Refresh the app to
            try again. If it keeps happening, copy the error details and send
            them to us.
          </Text>
          <code
            title={summary}
            className="mt-1 max-w-full truncate rounded-md border border-border bg-muted px-2 py-1 font-mono text-muted-foreground text-xs"
          >
            {summary}
          </code>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button
            type="button"
            variant="primary"
            data-attr="error-boundary-refresh"
            onClick={onRefresh}
          >
            <ArrowClockwise />
            Refresh app
          </Button>
          <Button
            type="button"
            variant="outline"
            data-attr="error-boundary-copy"
            onClick={copyReport}
          >
            {copied ? <Check className="text-success-foreground" /> : <Copy />}
            {copied ? "Copied" : "Copy error details"}
          </Button>
        </div>
        <Collapsible
          open={detailsOpen}
          onOpenChange={setDetailsOpen}
          className="flex w-full flex-col items-center gap-2"
        >
          <CollapsibleTrigger
            data-attr="error-boundary-details"
            className="w-auto text-muted-foreground"
          >
            {detailsOpen ? "Hide technical details" : "Show technical details"}
          </CollapsibleTrigger>
          <CollapsibleContent className="w-full">
            <pre className="max-h-56 select-text overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-3 text-left font-mono text-[11px] text-muted-foreground leading-relaxed">
              {report}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
