import { useValues } from 'kea'

import { pluralize } from 'lib/utils/strings'

import type { InsightLogicProps } from '~/types'

import { DataChecksPopover } from './DataChecksPopover'
import { DataChecksTag } from './DataChecksTag'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { InsightDataChecksStatus } from './insightDataChecksLogic'

function statusLabel(status: InsightDataChecksStatus, findingCount: number): string {
    switch (status) {
        case 'checking':
            return 'Checking data'
        case 'failed':
            return "Data checks didn't finish"
        case 'no_events':
            return 'No data to check'
        case 'inconclusive':
            return 'Data not checked'
        case 'warning':
            return pluralize(findingCount, 'data warning')
        case 'problem':
            return pluralize(findingCount, 'data issue')
        default:
            return 'No data issues found'
    }
}

export function InsightDataChecks({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { findings, labelOpen, status } = useValues(insightDataChecksLogic(insightProps))

    if (status === 'unavailable' || status === 'unsupported') {
        return null
    }

    const label = statusLabel(status, findings.length)
    return (
        <DataChecksPopover
            insightProps={insightProps}
            trigger={
                <button
                    type="button"
                    className="group/checks inline-flex cursor-pointer rounded-(--radius) border-0 bg-transparent p-0"
                    data-attr="insight-data-checks"
                    data-status={status}
                />
            }
        >
            <DataChecksTag status={status} label={label} labelOpen={labelOpen} />
        </DataChecksPopover>
    )
}
