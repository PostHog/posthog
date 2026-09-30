import { BindLogic } from 'kea'

import { TaskTrackerSceneLogicProps, taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { TaskComposer } from './TaskComposer'

export type EmbeddedTaskComposerImplProps = Required<Pick<TaskTrackerSceneLogicProps, 'panelId'>> &
    Pick<TaskTrackerSceneLogicProps, 'channelId' | 'initialRepositoryConfig' | 'composerOverride' | 'onTaskCreated'>

/**
 * The new-task composer alone, for a host page that lists tasks itself. It binds an embedded
 * `taskTrackerSceneLogic` instance keyed by `panelId`, so it never shares a draft with the `/tasks` scene.
 * It never renders the run: the host opens the created task from `onTaskCreated`.
 */
export function EmbeddedTaskComposerImpl(props: EmbeddedTaskComposerImplProps): JSX.Element {
    return (
        <BindLogic logic={taskTrackerSceneLogic} props={props}>
            <TaskComposer variant="inline" />
        </BindLogic>
    )
}
