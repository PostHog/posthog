import { CheckCircle } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";
import { ReportRow } from "@posthog/ui/features/canvas/components/ReportRow";
import { useInboxAvailable } from "@posthog/ui/features/feature-flags/useInboxAvailable";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { PANE_INSET } from "@posthog/ui/primitives/ChromeBar";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import {
  navigateToInbox,
  navigateToReport,
} from "@posthog/ui/router/navigationBridge";
import { useTodayReports } from "./useTodayReports";

const TODAY_DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  weekday: "long",
  month: "long",
  day: "numeric",
});

/** What needs the user now: Self-driving reports that name them, and the activity feed beside it. */
export function TodayView() {
  useSetHeaderContent(
    <div className="flex min-w-0 items-baseline gap-2">
      <span className="truncate font-medium text-sm">Today</span>
      <span className="truncate text-muted-foreground text-xs">
        {TODAY_DATE_FORMAT.format(new Date())}
      </span>
    </div>,
  );
  const inboxAvailable = useInboxAvailable();

  return (
    <div className="@container flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex min-h-0 flex-1 @3xl:flex-row flex-col">
        {inboxAvailable && (
          <section
            aria-label="Needs you"
            className={`flex min-w-0 flex-1 flex-col gap-2 py-4 ${PANE_INSET}`}
          >
            <NeedsYou />
          </section>
        )}
        <section
          aria-label="Activity"
          className="flex @3xl:h-auto h-[480px] min-h-0 @3xl:w-[360px] w-full shrink-0 flex-col border-border border-t @3xl:border-t-0 @3xl:border-l"
        >
          <ActivityFeedList className="min-h-0 flex-1" />
        </section>
      </div>
    </div>
  );
}

function NeedsYou() {
  const { reports, totalCount } = useTodayReports(true);

  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium text-sm">Needs you</h2>
        {totalCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={navigateToInbox}
            data-attr="today-view-all-reports"
          >
            View all in Self-driving
          </Button>
        )}
      </div>
      {reports === null ? (
        <LoadingState className="h-32" />
      ) : reports.length === 0 ? (
        <Empty className="border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <CheckCircle size={20} />
            </EmptyMedia>
            <EmptyTitle>Nothing needs you</EmptyTitle>
            <EmptyDescription>
              Self-driving reports that name you as a reviewer show up here.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="flex flex-col">
          {reports.map((report) => (
            <ReportRow
              key={report.id}
              report={report}
              isActive={false}
              onOpen={(reportId) => navigateToReport(reportId)}
            />
          ))}
        </div>
      )}
    </>
  );
}
