import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { pluralize } from 'lib/utils/strings'

import type { InsightLogicProps } from '~/types'

import { InsightDataChecksList } from './InsightDataChecksList'
import { insightDataChecksLogic } from './insightDataChecksLogic'
import type { InsightDataChecksStatus } from './insightDataChecksLogic'

function statusIcon(status: InsightDataChecksStatus): JSX.Element | null {
    switch (status) {
        case 'checking':
            return <Spinner textColored />
        case 'passed':
            return <IconCheck className="text-success" />
        case 'warning':
            return <IconWarning className="text-warning" />
        case 'problem':
        case 'failed':
            return <IconWarning className="text-danger" />
        default:
            return null
    }
}

function statusLabel(status: InsightDataChecksStatus, findingCount: number): string {
    switch (status) {
        case 'checking':
            return 'Checking data'
        case 'failed':
            return "Data checks didn't finish"
        case 'no_events':
            return 'No data to check'
        case 'warning':
        case 'problem':
            return pluralize(findingCount, 'data issue')
        default:
            return 'No data issues found'
    }
}

/** The result of the data checks on the events behind an insight. It opens the list of checks. */
export function InsightDataChecks({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { status, findings } = useValues(insightDataChecksLogic(insightProps))
    const { reportDataChecksViewed } = useActions(insightDataChecksLogic(insightProps))

    if (status === 'unavailable' || status === 'unsupported') {
        return null
    }

    return (
        <LemonDropdown
            overlay={<InsightDataChecksList insightProps={insightProps} />}
            placement="bottom-end"
            closeOnClickInside={false}
            onVisibilityChange={(visible) => {
                if (visible) {
                    reportDataChecksViewed()
                }
            }}
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={statusIcon(status)}
                data-attr="insight-data-checks"
                data-status={status}
            >
                {statusLabel(status, findings.length)}
            </LemonButton>
        </LemonDropdown>
    )
}
