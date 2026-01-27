import clsx from 'clsx'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock } from '@posthog/icons'
import { SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { Workflow } from './Workflow'
import { WorkflowLogs } from './WorkflowLogs'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneLogicProps, WorkflowTab, workflowSceneLogic } from './workflowSceneLogic'

export const scene: SceneExport<WorkflowSceneLogicProps> = {
    component: WorkflowScene,
    logic: workflowSceneLogic,
    paramsToProps: ({ params: { id, tab } }) => ({
        id: id || 'new',
        tab: tab || 'workflow',
    }),
    productKey: ProductKey.WORKFLOWS,
}

export function WorkflowScene(props: WorkflowSceneLogicProps): JSX.Element {
    const { currentTab } = useValues(workflowSceneLogic)
    const { searchParams } = useValues(router)
    const templateId = searchParams.templateId as string | undefined
    const editTemplateId = searchParams.editTemplateId as string | undefined

    const { futureJobs } = useValues(batchWorkflowJobsLogic({ id: props.id }))

    const logic = workflowLogic({ id: props.id, templateId, editTemplateId })
    const { workflowLoading, originalWorkflow } = useValues(logic)

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
            label: (
                <div className="flex gap-2">
                    Invocations
                    {futureJobs.length > 0 ? (
                        <span className="font-bold">
                            <IconClock /> {futureJobs.length}
                        </span>
                    ) : (
                        ''
                    )}
                </div>
            ),
            key: 'logs',
            content: <WorkflowLogs id={props.id!} />,
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
        <SceneContent className="h-full flex flex-col grow">
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
                    className={clsx({
                        'flex flex-col grow [&>div]:flex [&>div]:flex-col [&>div]:grow': currentTab === 'workflow',
                    })}
                />
            )}
        </SceneContent>
    )
}
