import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Dot, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { InsightLogicProps } from '~/types'

import { DataCheckRow } from './DataCheckRow'
import { CHECKED_DAYS } from './dataChecks'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { DataChecksStatus } from './insightDataChecksLogic'

const DOT_VARIANTS: Record<DataChecksStatus, 'default' | 'success' | 'warning' | 'destructive'> = {
    unavailable: 'default',
    checking: 'default',
    failed: 'default',
    empty: 'default',
    passed: 'success',
    warning: 'warning',
    problem: 'destructive',
}

function statusLabel(status: DataChecksStatus, findingCount: number): string {
    switch (status) {
        case 'checking':
            return 'Checking data'
        case 'failed':
            return "Data checks didn't run"
        case 'empty':
            return 'No data to check'
        case 'warning':
            return pluralize(findingCount, 'data warning')
        case 'problem':
            return pluralize(findingCount, 'data issue')
        default:
            return 'Data checks passed'
    }
}

/** Shows whether the events behind the chart look trustworthy, with each check listed on hover. */
export function InsightDataChecks({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const logic = insightDataChecksLogic(insightProps)
    const { checks, counts, findings, status } = useValues(logic)
    const { filterOutInternalUsers, loadChecksRun, reportDataChecksViewed } = useActions(logic)
    const titleId = useId()

    if (status === 'unavailable') {
        return null
    }

    return (
        <Popover
            onOpenChange={(open) => {
                if (open) {
                    reportDataChecksViewed()
                }
            }}
        >
            <PopoverTrigger
                openOnHover
                delay={150}
                closeDelay={150}
                render={<Button variant="outline" size="sm" data-attr="quill-insight-data-checks" />}
                data-status={status}
            >
                <Dot variant={DOT_VARIANTS[status]} pulse={status === 'checking'} />
                {statusLabel(status, findings.length)}
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 gap-3" aria-labelledby={titleId}>
                <Text id={titleId} size="sm" weight="medium">
                    Checks on this chart's data
                </Text>
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                    {checks.map((check) => (
                        <DataCheckRow key={check.key} check={check} onFilterInternalUsers={filterOutInternalUsers} />
                    ))}
                </ul>
                {status === 'failed' && (
                    <>
                        <Text size="xs" variant="muted">
                            The checks didn't run. Try again, and reload the page if it keeps happening.
                        </Text>
                        <Button
                            variant="outline"
                            size="sm"
                            className="self-start"
                            onClick={() => loadChecksRun()}
                            data-attr="quill-insight-data-checks-retry"
                        >
                            Try again
                        </Button>
                    </>
                )}
                {counts && counts.events > 0 && status !== 'checking' && (
                    <Text size="xs" variant="muted">
                        {`Checked ${humanFriendlyNumber(counts.events)} events that this chart reads. The checks cover the last ${CHECKED_DAYS} days at most.`}
                    </Text>
                )}
            </PopoverContent>
        </Popover>
    )
}
