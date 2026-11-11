import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'

import { notesButtonLabel, replayObservationSceneLogic } from './replayObservationSceneLogic'

export const NOTES_BUTTON_TOOLTIP =
    'Internal notes for your team. @-mention a teammate to notify them, or add a note as a task.'

/** Opens the observation's notes in the discussion side panel, so the page itself stays free of them. */
export function ObservationNotesButton(): JSX.Element {
    const { notesPanelOpen, notesDisabledReason } = useValues(replayObservationSceneLogic)
    const { commentCount } = useValues(sidePanelDiscussionLogic)
    const { toggleNotesPanel } = useActions(replayObservationSceneLogic)
    return (
        <LemonButton
            icon={<IconChat />}
            type="secondary"
            size="small"
            active={notesPanelOpen}
            onClick={toggleNotesPanel}
            disabledReason={notesDisabledReason}
            tooltip={NOTES_BUTTON_TOOLTIP}
            data-attr="vision-observation-notes"
        >
            {notesButtonLabel(notesDisabledReason, commentCount)}
        </LemonButton>
    )
}
