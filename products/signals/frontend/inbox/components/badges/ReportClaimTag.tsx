import { useValues } from 'kea'

import { LemonTag, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { SignalReport } from '../../types'
import { reportClaimant } from '../../utils/reportClaim'

/** Marks a report that a person claimed, so the list tells the user's own claims apart from a teammate's. */
export function ReportClaimTag({ report }: { report: Pick<SignalReport, 'assignee'> }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const claimant = reportClaimant(report)
    if (!claimant) {
        return null
    }
    const isMine = !!user?.uuid && claimant.uuid === user.uuid
    const name = fullNameOrEmail(claimant)

    return isMine ? (
        <Tooltip title="You claimed this report">
            <LemonTag type="success" size="small" data-attr="inbox-report-card-claim-tag">
                You're on it
            </LemonTag>
        </Tooltip>
    ) : (
        <Tooltip title={`${name} is working on this`}>
            <LemonTag
                size="small"
                icon={<ProfilePicture user={claimant} name={name} size="xs" />}
                data-attr="inbox-report-card-claim-tag"
            >
                <span className="max-w-32 truncate">{claimant.first_name || name}</span>
            </LemonTag>
        </Tooltip>
    )
}
