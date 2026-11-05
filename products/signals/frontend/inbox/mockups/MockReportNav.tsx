import { IconArrowLeft, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function MockReportNav({ position, total }: { position: number; total: number }): JSX.Element {
    return (
        <nav className="InboxMockup__nav" aria-label="Report navigation">
            <button type="button" className="TodayReportNav__back">
                <IconArrowLeft className="size-3.5" aria-hidden />
                <span>Inbox</span>
            </button>
            <span className="TodayReportNav__steps">
                <span className="TodayReportNav__count">
                    {position} of {total}
                </span>
                <Button variant="link-muted" size="icon-sm" aria-label="Previous report" tooltip="Previous report">
                    <IconChevronLeft />
                </Button>
                <Button variant="link-muted" size="icon-sm" aria-label="Next report" tooltip="Next report">
                    <IconChevronRight />
                </Button>
            </span>
        </nav>
    )
}
