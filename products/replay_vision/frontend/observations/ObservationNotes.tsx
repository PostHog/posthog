import { useValues } from 'kea'

import { CommentComposer } from 'lib/components/Comments/CommentComposer'
import { CommentsList } from 'lib/components/Comments/CommentsList'
import { CommentsLogicProps } from 'lib/components/Comments/commentsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import { LabeledRow } from '../components/LabeledRow'
import type { ReplayObservationApi } from '../generated/api.schemas'

export function ObservationNotes({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const { sidePanelOpen, selectedTab } = useValues(sidePanelStateLogic)
    const commentsLogicProps: CommentsLogicProps = {
        scope: ActivityScope.REPLAY_OBSERVATION,
        item_id: observation.id,
        item_context: {
            session_id: observation.session_id,
            scanner_id: observation.scanner_id,
        },
    }
    // The discussion panel shows these same notes, and two composers on one thread share one editor.
    const notesInSidePanel = sidePanelOpen && selectedTab === SidePanelTab.Discussion

    return (
        <LabeledRow
            label="Internal notes"
            tooltip="Only members of this project who can see this observation can read its notes. @-mention a teammate to notify them, or add the note as a task to assign follow-up."
        >
            {notesInSidePanel ? (
                <p className="text-muted m-0">The notes are open in the discussion panel.</p>
            ) : (
                <div className="flex flex-col gap-2">
                    <CommentsList {...commentsLogicProps} noun="observation" />
                    <CommentComposer {...commentsLogicProps} />
                </div>
            )}
        </LabeledRow>
    )
}
