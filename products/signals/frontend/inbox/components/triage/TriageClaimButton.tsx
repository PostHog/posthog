import { useActions, useValues } from 'kea'

import { IconPerson } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'

/** Assign to me, or Unassign once the report is yours. Each label shows its key, so the footer teaches both. */
export function TriageClaimButton(): JSX.Element {
    const { isCurrentAssignedToMe, isSavingClaimOnCurrent, assignDisabledReason } = useValues(inboxTriageLogic)
    const { assignCurrentToMe, unassignCurrent } = useActions(inboxTriageLogic)

    return isCurrentAssignedToMe ? (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconPerson />}
            onClick={() => unassignCurrent('button')}
            loading={isSavingClaimOnCurrent}
            sideIcon={<KeyboardShortcut command u />}
            data-attr="inbox-triage-unassign"
        >
            Unassign
        </LemonButton>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconPerson />}
            onClick={() => assignCurrentToMe('button')}
            loading={isSavingClaimOnCurrent}
            disabledReason={assignDisabledReason}
            sideIcon={<KeyboardShortcut u />}
            data-attr="inbox-triage-assign-to-me"
        >
            Assign to me
        </LemonButton>
    )
}
