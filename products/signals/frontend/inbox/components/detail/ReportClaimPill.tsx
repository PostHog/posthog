import { LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

export function ReportClaimPill({
    claimant,
    isClaimedByMe,
    claimedAt,
}: {
    claimant: _UserApi | null
    isClaimedByMe: boolean
    claimedAt: string | null
}): JSX.Element | null {
    if (!claimant) {
        return null
    }
    const name = fullNameOrEmail(claimant)

    return (
        <div>
            <LemonTag
                type="success"
                icon={<ProfilePicture user={claimant} name={name} size="xs" />}
                data-attr="inbox-report-claim-pill"
            >
                <span>{isClaimedByMe ? "You're working on this" : `${name} is working on this`}</span>
                {claimedAt && (
                    <>
                        <span aria-hidden>·</span>
                        <TZLabel time={claimedAt} />
                    </>
                )}
            </LemonTag>
        </div>
    )
}
