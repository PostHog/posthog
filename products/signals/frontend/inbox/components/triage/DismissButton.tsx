import { useActions } from 'kea'

import { IconHide } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'

export function DismissButton(): JSX.Element {
    const { dismissCurrent } = useActions(inboxTriageLogic)

    return (
        <LemonButton
            type="secondary"
            size="xsmall"
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
