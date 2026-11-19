// PROTOTYPE (throwaway): the calendar of an account with nothing scheduled, which is what most people see
// today. One card that says what lands here and how to start, instead of an empty month grid.
import { IconCalendar } from '@posthog/icons'
import { Button, Card } from '@posthog/quill'

export function CalendarEmptyState(): JSX.Element {
    return (
        <Card className="flex flex-col items-center gap-3 px-6 py-12 text-center">
            <IconCalendar className="size-8 text-muted-foreground" />
            <div className="flex max-w-md flex-col gap-1">
                <h3 className="mb-0 text-base font-semibold">Nothing is scheduled yet</h3>
                <p className="mb-0 text-sm text-muted-foreground">
                    Scheduled broadcasts and messaging workflows show here by day, next to how many transactional emails
                    went out. Schedule a broadcast or turn on a workflow to see it here.
                </p>
            </div>
            <div className="flex gap-2">
                <Button variant="primary">New broadcast</Button>
                <Button variant="outline">New workflow</Button>
            </div>
        </Card>
    )
}
