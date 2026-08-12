import { Text } from "@posthog/quill";
import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { PRBadgeLink } from "@posthog/ui/features/git-interaction/components/PRBadgeLink";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";

/**
 * The pull requests a ticket points at: ones attached to it by hand, then ones
 * its agent thread opened.
 *
 * State comes from Desktop's own pull-request status for the linked task, which
 * is the only source available here. A link with no task behind it is shown
 * without a state rather than with a guessed one — the reference is still worth
 * having, and claiming "Open" for a pull request that merged last week would be
 * worse than saying nothing.
 */
export function TicketPullRequests({
  prUrls,
  task,
}: {
  prUrls: string[];
  task: Task | undefined;
}) {
  const taskPrUrls = readPrUrls(task?.latest_run?.output);
  const status = useTaskPrStatus({
    id: task?.id ?? "",
    cloudPrUrl: taskPrUrls[0] ?? null,
    taskRunEnvironment: task?.latest_run?.environment ?? null,
  });

  if (prUrls.length === 0) {
    return <Text className="text-[12px] text-muted-foreground">None</Text>;
  }

  return (
    <div className="flex flex-wrap justify-end gap-1">
      {prUrls.map((prUrl) => {
        const hasState = status.prState !== null && taskPrUrls.includes(prUrl);

        return hasState ? (
          <PRBadgeLink
            key={prUrl}
            prUrl={prUrl}
            prState={status.prState === "closed" ? "closed" : "open"}
            merged={status.prState === "merged"}
            draft={status.prState === "draft"}
            compact
          />
        ) : (
          <PrReferenceLink key={prUrl} prUrl={prUrl} />
        );
      })}
    </div>
  );
}

/** A pull request we have no state for: the same chip the sidebar's task rows use. */
function PrReferenceLink({ prUrl }: { prUrl: string }) {
  const number = prUrl.match(/\/pull\/(\d+)/)?.[1];

  return (
    <a
      href={prUrl}
      target="_blank"
      rel="noreferrer"
      className="inline-flex h-4 shrink-0 items-center gap-0.5 rounded bg-gray-3 px-1 text-[11px] text-gray-11 no-underline transition-colors hover:bg-gray-4 hover:text-gray-12"
    >
      {number ? `#${number}` : "Pull request"}
    </a>
  );
}
