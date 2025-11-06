import { useValues } from 'kea'
import { router } from 'kea-router'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { Workflow } from './Workflow'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
import { renderWorkflowLogMessage } from './logs/log-utils'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps, WorkflowTab, workflowSceneLogic } from './workflowSceneLogic'

export const scene: SceneExport<WorkflowSceneLogicProps> = {
    component: WorkflowScene,
    logic: workflowSceneLogic,
    paramsToProps: ({ params: { id, tab } }) => ({ id: id || 'new', tab: tab || 'workflow' }),
}

export function WorkflowScene(props: WorkflowSceneLogicProps): JSX.Element {
    const { currentTab } = useValues(workflowSceneLogic)

    const logic = workflowLogic(props)
    const { workflowLoading, workflow, originalWorkflow } = useValues(logic)

    if (!originalWorkflow && workflowLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (!originalWorkflow) {
        return <NotFound object="workflow" />
    }

    const tabs: (LemonTab<WorkflowTab> | null)[] = [
        {
            label: 'Workflow',
            key: 'workflow',
            content: <Workflow {...props} />,
        },

        {
            label: 'Logs',
            key: 'logs',
            content: (
                <LogsViewer
                    sourceType="hog_flow"
                    /**
                     * If we're rendering tabs, props.id is guaranteed to be
                     * defined and not "new" (see return statement below)
                     */
                    sourceId={props.id!}
                    instanceLabel="workflow run"
                    renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
                />
            ),
        },
        {
            label: 'Metrics',
            key: 'metrics',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <WorkflowMetrics id={props.id!} />,
        },
    ]

    return (
        <SceneContent className="flex flex-col">
            <WorkflowSceneHeader {...props} />
            {/* Only show Logs and Metrics tabs if the workflow has already been created */}
            {!props.id || props.id === 'new' ? (
                <Workflow {...props} />
            ) : (
                <LemonTabs
                    activeKey={currentTab}
                    onChange={(tab) => router.actions.push(urls.workflow(props.id ?? 'new', tab))}
                    tabs={tabs}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}
