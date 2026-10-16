import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { SendCalendarList } from './SendCalendarList'
import { sendCalendarLogic } from './sendCalendarLogic'
import { SendCalendarMonth } from './SendCalendarMonth'
import { CalendarTypeFilter, CalendarView } from './sendCalendarUtils'
import { SendCalendarWeek } from './SendCalendarWeek'

export function SendCalendar(): JSX.Element {
    const { view, typeFilter, periodLabel, timezone, scheduledFlows, scheduledFlowsLoading, loadFailed } =
        useValues(sendCalendarLogic)
    const { setView, setTypeFilter, goToToday, goForward, goBackward } = useActions(sendCalendarLogic)

    return (
        <div className="@container flex flex-col gap-2" data-attr="send-calendar">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-1">
                    <LemonButton type="secondary" size="small" onClick={goToToday} data-attr="send-calendar-today">
                        Today
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={goBackward}
                        tooltip={view === 'month' ? 'Previous month' : 'Previous week'}
                        data-attr="send-calendar-previous"
                    />
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight />}
                        onClick={goForward}
                        tooltip={view === 'month' ? 'Next month' : 'Next week'}
                        data-attr="send-calendar-next"
                    />
                    <h3 className="mb-0 ml-1 text-base font-semibold">{periodLabel}</h3>
                </div>
                <div className="flex items-center gap-2">
                    <LemonSegmentedButton<CalendarView>
                        size="small"
                        value={view}
                        onChange={setView}
                        options={[
                            { value: 'month', label: 'Month' },
                            { value: 'week', label: 'Week' },
                        ]}
                        data-attr="send-calendar-view"
                    />
                    <LemonSelect<CalendarTypeFilter>
                        size="small"
                        value={typeFilter}
                        onChange={setTypeFilter}
                        dropdownMatchSelectWidth={false}
                        options={[
                            { value: 'all', label: 'All sends' },
                            { value: 'broadcasts', label: 'Broadcasts' },
                            { value: 'workflows', label: 'Workflows' },
                        ]}
                        data-attr="send-calendar-type"
                    />
                </div>
            </div>
            <div className="text-xs text-secondary">
                Times use the project time zone ({timezone}). Drafts and event-triggered workflows do not show.
            </div>
            {scheduledFlowsLoading && !scheduledFlows ? (
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : loadFailed ? (
                <div className="rounded border bg-surface-primary p-8 text-center text-secondary">
                    Couldn't load the scheduled sends. Refresh the page to try again.
                </div>
            ) : !scheduledFlows?.length ? (
                <div className="rounded border bg-surface-primary p-8 text-center text-secondary">
                    Nothing is scheduled yet. Active broadcasts, and scheduled workflows with an email step, show here.
                </div>
            ) : (
                <>
                    <div className="hidden @min-[40rem]:block">
                        {view === 'month' ? <SendCalendarMonth /> : <SendCalendarWeek />}
                    </div>
                    <div className="@min-[40rem]:hidden">
                        <SendCalendarList />
                    </div>
                </>
            )}
        </div>
    )
}
