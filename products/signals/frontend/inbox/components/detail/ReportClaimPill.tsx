import { useValues } from 'kea'

import { LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { fullNameOrEmail } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import type { SignalReportAssigneeApi } from 'products/signals/frontend/generated/api.schemas'

import { reportClaimOwner } from '../../utils/reportClaim'

export function ReportClaimPill({
    assignee,
}: {
    assignee: SignalReportAssigneeApi | null | undefined
}): JSX.Element | null {
    const { user } = useValues(userLogic)
    const owner = reportClaimOwner(assignee)
    if (!assignee || !owner) {
        return null
    }
    const name = fullNameOrEmail(owner)
    const isMine = !!user?.uuid && owner.uuid === user.uuid
    const label =
        assignee.kind === 'agent'
            ? isMine
                ? 'Your agent is working on this'
                : `${name}'s agent is working on this`
            : isMine
              ? "You're working on this"
              : `${name} is working on this`

    return (
        <div>
            <LemonTag
                type="success"
                icon={<ProfilePicture user={owner} name={name} size="xs" />}
                data-attr="inbox-report-claim-pill"
            >
                <span>{label}</span>
                {assignee.claimed_at && (
                    <>
                        <span aria-hidden>·</span>
                        <TZLabel time={assignee.claimed_at} />
                    </>
                )}
            </LemonTag>
        </div>
    )
}
