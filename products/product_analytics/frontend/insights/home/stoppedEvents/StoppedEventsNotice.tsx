import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonCard } from '@posthog/lemon-ui'

import { StoppedEventRow } from './StoppedEventRow'
import { stoppedEventsLogic } from './stoppedEventsLogic'

/** Events that the product's insights read, which stopped arriving. Renders nothing until there is one to show. */
export function StoppedEventsNotice(): JSX.Element | null {
    const { visibleIssues } = useValues(stoppedEventsLogic)

    // The notice is optional, so it stays out of the layout while loading and when nothing stopped.
    if (!visibleIssues?.length) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="mb-4 overflow-hidden p-0" data-attr="stopped-events-notice">
            <div className="flex items-center gap-2 border-b border-primary px-4 py-2.5">
                <IconWarning className="size-4 text-warning" />
                <h2 className="m-0 text-sm font-semibold">
                    {visibleIssues.length === 1
                        ? 'An event your insights use stopped arriving'
                        : `${visibleIssues.length} events your insights use stopped arriving`}
                </h2>
            </div>
            <ul className="m-0 list-none p-0">
                {visibleIssues.map((issue) => (
                    <StoppedEventRow key={issue.id} issue={issue} />
                ))}
            </ul>
        </LemonCard>
    )
}
