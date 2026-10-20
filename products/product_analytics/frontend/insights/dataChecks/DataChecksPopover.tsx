import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Dot, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { InsightLogicProps } from '~/types'

import type { InsightDataChecksCoverageApi } from 'products/product_analytics/frontend/generated/api.schemas'

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
    const { checks, checkedQuery, result, status } = useValues(logic)
    const { loadDataChecks, reportDataChecksViewed } = useActions(logic)
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
                className="w-80 gap-2"
                aria-labelledby={titleId}
                data-attr="insight-data-checks-list"
            >
                <Text id={titleId} size="sm" weight="medium">
                    Checks we've run on this data
                </Text>
                <ul className="-mx-2 my-0 flex list-none flex-col p-0">
                    {status === 'checking'
                        ? Object.entries(DATA_CHECK_NAMES).map(([key, name]) => (
                              <li key={key} className="flex items-start gap-2 px-2 py-1">
                                  <span className="flex h-5 w-4 shrink-0 items-center justify-center">
                                      <Dot variant="default" pulse />
                                  </span>
                                  <Text size={null} variant="muted" render={<span />}>
                                      {name}
                                  </Text>
                              </li>
                          ))
                        : checks.map((check) => (
                              <InsightDataCheckRow key={check.key} insightProps={insightProps} check={check} />
                          ))}
                </ul>
                <Text size="xs" variant="muted">
                    {summary(status, result?.coverage)}
                </Text>
                {status === 'failed' && (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => checkedQuery && loadDataChecks(checkedQuery)}
                        data-attr="insight-data-checks-retry"
                    >
                        Try again
                    </Button>
                )}
            </PopoverContent>
        </Popover>
    )
}
