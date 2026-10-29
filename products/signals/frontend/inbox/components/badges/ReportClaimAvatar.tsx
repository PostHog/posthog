import clsx from 'clsx'

import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import type { ReportClaim } from './useReportClaim'

/** The claimer's avatar on a report card. A ring marks the user's own claims apart from a teammate's. */
export function ReportClaimAvatar({ claim }: { claim: ReportClaim }): JSX.Element {
    return (
        <Tooltip title={claim.tooltip}>
            <span className="inline-flex shrink-0" data-attr="inbox-report-card-claim-tag">
                <ProfilePicture
                    user={claim.person}
                    name={claim.name}
                    size="sm"
                    className={clsx('rounded-full', claim.isMine && 'ring-3 ring-(--success)')}
                />
            </span>
        </Tooltip>
    )
}
