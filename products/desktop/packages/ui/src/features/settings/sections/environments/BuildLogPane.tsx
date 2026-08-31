import { Button, Text } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { useSandboxCustomImageDetail } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useCallback, useEffect, useRef } from "react";

interface BuildLogPaneProps {
  image: SandboxCustomImage;
}

/** The build's output, pinned to the bottom while it streams. */
export function BuildLogPane({ image }: BuildLogPaneProps) {
  const { data, isLoading, error, isFetching, refetch } =
    useSandboxCustomImageDetail(image.id);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const buildLog = data?.build_log ?? "";
  const status = data?.status ?? image.status;

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run as the log grows to keep the scroll pinned
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [buildLog]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  if (isLoading) {
    return (
      <Text className="text-(--gray-10) text-[11.5px]">Loading build log…</Text>
    );
  }

  if (!buildLog) {
    // Only when there is nothing cached to show: a later refetch failure keeps
    // the prior log visible, so it must not replace it with this error state.
    if (error) {
      return (
        <div className="flex flex-col items-start gap-2">
          <Text className="text-(--gray-10) text-[11.5px]">
            Couldn't load the build log.
          </Text>
          <Button
            variant="outline"
            size="sm"
            loading={isFetching}
            disabled={isFetching}
            data-attr="build-log-retry"
            onClick={() => void refetch()}
          >
            Try again
          </Button>
        </div>
      );
    }
    return (
      <Text className="text-(--gray-10) text-[11.5px]">
        {status === "scanning"
          ? "Security scan in progress. Build output streams once the build starts."
          : status === "building"
            ? "Waiting for build output…"
            : "No build log yet."}
      </Text>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="max-h-[280px] overflow-auto rounded-(--radius-3) border border-border bg-(--gray-2) p-2.5"
    >
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-(--gray-11) text-[11px] leading-relaxed">
        {buildLog}
      </pre>
    </div>
  );
}
