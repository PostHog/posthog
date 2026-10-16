import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { LostVisitorIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { LikelihoodSignal } from './LikelihoodSignal'

export function LostVisitorSignal({ issue }: { issue: LostVisitorIssue }): JSX.Element {
    return (
        <LikelihoodSignal
            rate={issue.rate}
            expectedRate={issue.expected_rate}
            caption="as likely to leave and not come back"
            explanation={`${share(issue.rate)} of ${humanFriendlyLargeNumber(issue.pageviews)} pageviews with this error ended the visit, and the visitor did not come back within a day. On the same pages without an error, with the same browsers and devices, ${share(issue.expected_rate)} did.`}
        />
    )
}
