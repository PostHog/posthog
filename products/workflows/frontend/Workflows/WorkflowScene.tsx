import clsx from 'clsx'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock } from '@posthog/icons'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
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
    paramsToProps: ({ params: { id, tab }, searchParams }) => ({
        id: id || 'new',
        tab: tab || 'workflow',
        templateId: searchParams.templateId as string | undefined,
        editTemplateId: searchParams.editTemplateId as string | undefined,
    }),
}

export function WorkflowScene(props: WorkflowSceneLogicProps): JSX.Element {
    const sceneLogic = workflowSceneLogic(props)
    const { currentTab } = useValues(sceneLogic)

    const batchJobsLogic = batchWorkflowJobsLogic({ id: props.id })
    const { futureJobs } = useValues(batchJobsLogic)

    // Construct complete logic props with all needed fields
    // templateId and editTemplateId come from props (via paramsToProps) which are tab-specific
    const logicProps = {
        id: props.id,
        templateId: props.templateId,
        editTemplateId: props.editTemplateId,
        tabId: props.tabId,
    }
    const logic = workflowLogic(logicProps)

    // Attach child logics to the scene logic so they persist across tab switches
    useAttachedLogic(batchJobsLogic, sceneLogic)
    useAttachedLogic(logic, sceneLogic)

    const tabs: (LemonTab<WorkflowTab> | null)[] = [
        {
            label: 'Workflow',
            key: 'workflow',
            content: <Workflow {...logicProps} />,
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
                <Workflow {...logicProps} />
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
