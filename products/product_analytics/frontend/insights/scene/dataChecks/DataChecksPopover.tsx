import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { InsightLogicProps } from '~/types'

import { DataCheckRow } from './DataCheckRow'
import { CHECKED_DAYS } from './dataChecks'
import type { DataCheckCounts } from './dataChecks'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { DataChecksStatus } from './insightDataChecksLogic'

function summary(status: DataChecksStatus, counts: DataCheckCounts | null): string {
    if (status === 'checking') {
        return 'Checking the events that this chart reads.'
    }
    if (status === 'failed') {
        return "The checks didn't run. Try again, and reload the page if it keeps happening."
    }
    if (!counts?.events) {
        return `No events from the last ${CHECKED_DAYS} days to check.`
    }
    return `${humanFriendlyNumber(counts.events)} events checked, from the last ${CHECKED_DAYS} days at most.`
}

export interface DataChecksPopoverProps {
    insightProps: InsightLogicProps
    trigger: React.ReactElement
    align: 'start' | 'end'
    children: React.ReactNode
}

export function DataChecksPopover({ insightProps, trigger, align, children }: DataChecksPopoverProps): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { checks, counts, status } = useValues(logic)
    const { filterOutInternalUsers, loadChecksRun, reportDataChecksViewed } = useActions(logic)
    const titleId = useId()

    return (
        <Popover
            onOpenChange={(open) => {
                if (open) {
                    reportDataChecksViewed()
                }
            }}
        >
            <PopoverTrigger openOnHover delay={150} closeDelay={150} render={trigger}>
                {children}
            </PopoverTrigger>
            <PopoverContent align={align} className="w-80 gap-2" aria-labelledby={titleId}>
                <Text id={titleId} size="sm" weight="medium">
                    Checks we've run on this data
                </Text>
                <ul className="-mx-2 my-0 flex list-none flex-col p-0">
                    {checks.map((check) => (
                        <DataCheckRow
                            key={check.key}
                            insightProps={insightProps}
                            check={check}
                            onFilterInternalUsers={filterOutInternalUsers}
                        />
                    ))}
                </ul>
                <Text size="xs" variant="muted">
                    {summary(status, counts)}
                </Text>
                {status === 'failed' && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => loadChecksRun()}
                        data-attr="quill-insight-data-checks-retry"
                    >
                        Try again
                    </Button>
                )}
            </PopoverContent>
        </Popover>
    )
}
