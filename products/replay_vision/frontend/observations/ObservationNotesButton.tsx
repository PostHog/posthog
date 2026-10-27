import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { replayObservationSceneLogic } from './replayObservationSceneLogic'

const NOTES_TOOLTIP = 'Internal notes for your team. @-mention a teammate to notify them, or add a note as a task.'

function useNotesButton(): { label: string; open: boolean; disabledReason: string | null; toggle: () => void } {
    const { notesDisabledReason } = useValues(replayObservationSceneLogic)
    const { commentCount } = useValues(sidePanelDiscussionLogic)
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const open = sidePanelOpen && selectedTab === SidePanelTab.Discussion
    return {
        label: !notesDisabledReason && commentCount > 0 ? `Notes (${commentCount})` : 'Notes',
        open,
        disabledReason: notesDisabledReason,
        toggle: () => (open ? closeSidePanel() : openSidePanel(SidePanelTab.Discussion)),
    }
}

/** Opens the observation's notes in the discussion side panel, so the page itself stays free of them. */
export function ObservationNotesButton(): JSX.Element {
    const { label, open, disabledReason, toggle } = useNotesButton()
    return (
        <LemonButton
            icon={<IconChat />}
            type="secondary"
            size="small"
            active={open}
            onClick={toggle}
            disabledReason={disabledReason}
            tooltip={NOTES_TOOLTIP}
            data-attr="vision-observation-notes"
        >
            {label}
        </LemonButton>
    )
}

export function QuillObservationNotesButton(): JSX.Element {
    const { label, open, disabledReason, toggle } = useNotesButton()
    return (
        <Button
            variant="outline"
            aria-pressed={open}
            onClick={toggle}
            disabledReason={disabledReason ?? undefined}
            tooltip={NOTES_TOOLTIP}
            data-attr="vision-observation-notes"
        >
            <IconChat />
            {label}
        </Button>
    )
}
