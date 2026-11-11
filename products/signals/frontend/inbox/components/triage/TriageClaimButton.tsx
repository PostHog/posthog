import { useActions, useValues } from 'kea'

import { IconPerson } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'

/** Claim, or Unclaim once the report is yours. Each label shows its key, so the footer teaches both. */
export function TriageClaimButton(): JSX.Element {
    const { isCurrentClaimedByMe, isSavingClaimOnCurrent, claimDisabledReason } = useValues(inboxTriageLogic)
    const { claimCurrent, unclaimCurrent } = useActions(inboxTriageLogic)

    return isCurrentClaimedByMe ? (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconPerson />}
            onClick={() => unclaimCurrent('button')}
            loading={isSavingClaimOnCurrent}
            sideIcon={<KeyboardShortcut command u />}
            data-attr="inbox-triage-unclaim"
        >
            Unclaim
        </LemonButton>
    ) : (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconPerson />}
            onClick={() => claimCurrent('button')}
            loading={isSavingClaimOnCurrent}
            disabledReason={claimDisabledReason}
            sideIcon={<KeyboardShortcut u />}
            data-attr="inbox-triage-claim"
        >
            Claim
        </LemonButton>
    )
}
