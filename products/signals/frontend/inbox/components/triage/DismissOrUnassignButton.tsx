import { useActions, useValues } from 'kea'

import { IconHide } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'

/**
 * The footer has no room for another button, so Unassign me takes the Dismiss slot while the command
 * key is held, and the reader sees what the chord will do before U is pressed. Unassign me has no icon
 * so that it fits the width Dismiss leaves free: a wider button would wrap the row each time the key
 * goes down.
 */
export function DismissOrUnassignButton({ commandKeyHeld }: { commandKeyHeld: boolean }): JSX.Element {
    const { unassignDisabledReason, isUnassigningCurrent } = useValues(inboxTriageLogic)
    const { dismissCurrent, unassignCurrent } = useActions(inboxTriageLogic)

    return commandKeyHeld ? (
        <LemonButton
            type="secondary"
            size="small"
            onClick={unassignCurrent}
            loading={isUnassigningCurrent}
            disabledReason={unassignDisabledReason}
            sideIcon={<KeyboardShortcut command u />}
            data-attr="inbox-triage-unassign-me"
        >
            Unassign me
        </LemonButton>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconHide />}
            onClick={dismissCurrent}
            sideIcon={<KeyboardShortcut a />}
            // pinned: data-attr predates the Archive → Dismiss rename; dashboards read it.
            data-attr="inbox-triage-archive"
        >
            Dismiss
        </LemonButton>
    )
}
