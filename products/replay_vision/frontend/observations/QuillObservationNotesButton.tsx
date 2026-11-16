import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'

import { NOTES_BUTTON_TOOLTIP } from './ObservationNotesButton'
import { notesButtonLabel, replayObservationSceneLogic } from './replayObservationSceneLogic'

export function QuillObservationNotesButton(): JSX.Element {
    const { notesPanelOpen, notesDisabledReason } = useValues(replayObservationSceneLogic)
    const { commentCount } = useValues(sidePanelDiscussionLogic)
    const { toggleNotesPanel } = useActions(replayObservationSceneLogic)
    return (
        <Button
            variant="outline"
            aria-pressed={notesPanelOpen}
            onClick={toggleNotesPanel}
            disabledReason={notesDisabledReason ?? undefined}
            tooltip={NOTES_BUTTON_TOOLTIP}
            data-attr="vision-observation-notes"
        >
            <IconChat />
            {notesButtonLabel(notesDisabledReason, commentCount)}
        </Button>
    )
}
