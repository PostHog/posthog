import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { QuickLeaveIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { LikelihoodSignal } from './LikelihoodSignal'

export interface QuickLeaveSignalProps {
    issue: QuickLeaveIssue
    // Both groups only count pageviews that lasted this long, so leaving quickly means leaving before
    // minPageSeconds + quickLeaveSeconds.
    minPageSeconds: number
    quickLeaveSeconds: number
}

export function QuickLeaveSignal({ issue, minPageSeconds, quickLeaveSeconds }: QuickLeaveSignalProps): JSX.Element {
    const returned =
        issue.returned_rate !== null
            ? ` ${share(issue.returned_rate)} of the people who left came back within a day.`
            : ''
    return (
        <LikelihoodSignal
            rate={issue.rate}
            expectedRate={issue.expected_rate}
            caption={`as likely to leave within ${minPageSeconds + quickLeaveSeconds}s`}
            explanation={`${share(issue.rate)} of ${humanFriendlyLargeNumber(issue.pageviews)} pageviews with this error ended between ${minPageSeconds} and ${minPageSeconds + quickLeaveSeconds} seconds after the page opened. On the same pages without an error, with the same browsers and devices, ${share(issue.expected_rate)} did. This usually means the page did not load properly.${returned}`}
        />
    )
}
