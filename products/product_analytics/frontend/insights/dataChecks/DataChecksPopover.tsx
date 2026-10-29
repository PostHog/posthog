import { useActions, useMountedLogic, useValues } from 'kea'
import { useId } from 'react'

import {
    Accordion,
    Button,
    Dot,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Skeleton,
    Spinner,
    Text,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { InsightLogicProps } from '~/types'

import type { InsightDataChecksCoverageApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { DataChecksFeedback } from './DataChecksFeedback'
import { dataChecksFeedbackLogic } from './dataChecksFeedbackLogic'
import { DATA_CHECK_NAMES } from './dataCheckText'
import { InsightDataCheckRow } from './InsightDataCheckRow'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { InsightDataChecksStatus } from './insightDataChecksLogic'

function summary(status: InsightDataChecksStatus, coverage: InsightDataChecksCoverageApi | null | undefined): string {
    if (status === 'checking') {
        return 'Checking the events that this chart reads.'
    }
    if (status === 'failed') {
        return "The checks didn't finish. The chart's own numbers are not affected."
    }
    if (status === 'on_request') {
        return "Checking this chart's events reads a lot of data, so the checks don't run on their own."
    }
    if (!coverage) {
        return 'No check could run on this chart.'
    }
    const days = pluralize(coverage.days_checked, 'day')
    if (coverage.events_checked === 0) {
        return `No events in the newest ${days} of this chart, so there is nothing to check.`
    }
    if (coverage.events_checked === null) {
        return `Checked the events from the newest ${days} of this chart.`
    }
    return `Checked ${humanFriendlyNumber(coverage.events_checked)} events from the newest ${days} of this chart.`
}

export interface DataChecksPopoverProps {
    insightProps: InsightLogicProps
    trigger: React.ReactElement
    children: React.ReactNode
}

export function DataChecksPopover({ insightProps, trigger, children }: DataChecksPopoverProps): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { visibleChecks, checkedQuery, result, status, canRunFullCheck } = useValues(logic)
    const { loadDataChecks, reportButtonClicked, reportDataChecksViewed, runFullCheck } = useActions(logic)
    const { user } = useValues(userLogic)
    const userId = user?.uuid ?? ''
    // Mounted outside the popover content, so a half-written note survives the popover closing.
    useMountedLogic(dataChecksFeedbackLogic({ userId }))
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
            <PopoverContent
                align="end"
                className="w-96 gap-2"
                aria-labelledby={titleId}
                data-attr="insight-data-checks-list"
            >
                <Text id={titleId} size="sm" weight="medium">
                    {status === 'on_request' ? 'Checks we can run on this data' : "Checks we've run on this data"}
                </Text>
                {/* Every check waits for the same request, so the reason is said once, below the list. */}
                {visibleChecks.length > 0 && status !== 'on_request' ? (
                    <Accordion>
                        {visibleChecks.map((check) => (
                            <InsightDataCheckRow key={check.key} insightProps={insightProps} check={check} />
                        ))}
                    </Accordion>
                ) : (
                    (status === 'checking' || status === 'on_request') && (
                        <ul className="-mx-2 my-0 flex list-none flex-col p-0">
                            {Object.entries(DATA_CHECK_NAMES).map(([key, name]) => (
                                <li key={key} className="flex items-start gap-2 px-2 py-1">
                                    <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                                        {status === 'checking' ? (
                                            <Spinner aria-hidden className="text-(--muted-foreground)" />
                                        ) : (
                                            <Dot variant="default" />
                                        )}
                                    </span>
                                    <span className="flex flex-col">
                                        <Text size={null} weight="medium" render={<span />}>
                                            {name}
                                        </Text>
                                        {status === 'checking' && (
                                            <span className="flex h-4 items-center">
                                                <Skeleton className="h-2.5 w-28" />
                                            </span>
                                        )}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )
                )}
                <Text size="xs" variant="muted">
                    {summary(status, result?.coverage)}
                </Text>
                {status === 'failed' && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => {
                            reportButtonClicked('retry')
                            if (checkedQuery) {
                                loadDataChecks(checkedQuery)
                            }
                        }}
                        data-attr="insight-data-checks-retry"
                    >
                        Try again
                    </Button>
                )}
                {canRunFullCheck && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => checkedQuery && runFullCheck(checkedQuery)}
                        data-attr="insight-data-checks-run-full"
                    >
                        Run a full check
                    </Button>
                )}
                {(status === 'passed' || status === 'warning' || status === 'problem' || status === 'partial') && (
                    <DataChecksFeedback userId={userId} />
                )}
            </PopoverContent>
        </Popover>
    )
}
