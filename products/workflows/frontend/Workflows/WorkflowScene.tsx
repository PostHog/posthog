import { useValues } from 'kea'
import { router } from 'kea-router'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ActivityScope } from '~/types'

import { Workflow } from './Workflow'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
import { WorkflowTemplate } from './WorkflowTemplate'
import { WorkflowTemplateEditingSceneHeader } from './WorkflowTemplateEditingSceneHeader'
import { renderWorkflowLogMessage } from './logs/log-utils'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps, WorkflowTab, workflowSceneLogic } from './workflowSceneLogic'
import { workflowTemplateEditingLogic } from './workflowTemplateEditingLogic'

export const scene: SceneExport<WorkflowSceneLogicProps> = {
    component: WorkflowScene,
    logic: workflowSceneLogic,
    paramsToProps: ({ params: { id, tab } }) => ({
        id: id || 'new',
        tab: tab || 'workflow',
    }),
}

export function WorkflowScene(props: WorkflowSceneLogicProps): JSX.Element {
    const { currentTab } = useValues(workflowSceneLogic)
    const { searchParams } = useValues(router)
    const editTemplateId = searchParams.editTemplateId as string | undefined

    // Use template editor logic when editing a template, otherwise use workflow logic
    const isTemplateEdit = !!editTemplateId

    const { workflowLoading, workflow, originalWorkflow } = useValues(workflowLogic({ id: props.id }))
    const { template, templateLoading } = useValues(workflowTemplateEditingLogic({ editTemplateId }))

    const isLoading = isTemplateEdit ? workflowLoading : templateLoading
    const hasData = isTemplateEdit ? template : originalWorkflow

    if (isLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (!hasData) {
        // TODOdin: Test this for template
        return <NotFound object={isTemplateEdit ? 'template' : 'workflow'} />
    }

    const tabs: (LemonTab<WorkflowTab> | null)[] = [
        {
            label: 'Workflow',
            key: 'workflow',
            content: <Workflow id={props.id} />,
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
        {
            label: 'History',
            key: 'history',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <ActivityLog id={props.id!} scope={ActivityScope.HOG_FLOW} />,
        },
    ]

    return (
        <SceneContent className="flex flex-col">
            {isTemplateEdit && editTemplateId ? (
                <WorkflowTemplateEditingSceneHeader editTemplateId={editTemplateId} workflowProps={props} />
            ) : (
                <WorkflowSceneHeader {...props} />
            )}
            {/* Only show Logs and Metrics tabs if the workflow has already been created and we're not editing a template */}
            {isTemplateEdit ? (
                <WorkflowTemplate editTemplateId={editTemplateId} />
            ) : !props.id || props.id === 'new' ? (
                <Workflow id={props.id} />
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
