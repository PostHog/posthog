import { CommentComposer } from 'lib/components/Comments/CommentComposer'
import { CommentsList } from 'lib/components/Comments/CommentsList'
import { CommentsLogicProps } from 'lib/components/Comments/commentsLogic'

import { ActivityScope } from '~/types'

import { LabeledRow } from '../components/LabeledRow'
import type { ReplayObservationApi } from '../generated/api.schemas'

export function ObservationNotes({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    const commentsLogicProps: CommentsLogicProps = {
        scope: ActivityScope.REPLAY_OBSERVATION,
        item_id: observation.id,
        item_context: {
            session_id: observation.session_id,
            scanner_id: observation.scanner_id,
        },
    }

    return (
        <LabeledRow
            label="Internal notes"
            tooltip="Only members of this project can see notes. @-mention a teammate to notify them, or add the note as a task to assign follow-up."
        >
            <div className="flex flex-col gap-2">
                <CommentsList {...commentsLogicProps} noun="observation" />
                <CommentComposer {...commentsLogicProps} />
            </div>
        </LabeledRow>
    )
}
