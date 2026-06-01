import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { BlockedRunsBanner } from './BlockedRunsBanner'
import { BlockedRunsReplay } from './BlockedRunsReplay'
import { Workflow } from './Workflow'
import { workflowLogic } from './workflowLogic'
import { WorkflowLogs } from './WorkflowLogs'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
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
    const workflowSceneProps: WorkflowSceneLogicProps = {
        id: props.id || 'new',
        tab: props.tab || 'workflow',
        tabId: props.tabId || 'default',
    }
    const sceneLogic = workflowSceneLogic(workflowSceneProps)
    const { currentTab } = useValues(sceneLogic)
    const { searchParams } = useValues(router)
    const templateId = searchParams.templateId as string | undefined
    const editTemplateId = searchParams.editTemplateId as string | undefined

    const batchJobsLogic = batchWorkflowJobsLogic({ id: workflowSceneProps.id })

    const logic = workflowLogic({ id: props.id, tabId: props.tabId, templateId, editTemplateId })
    const { workflowLoading, originalWorkflow } = useValues(logic)

    const showBlockedRuns = useFeatureFlag('WORKFLOWS_REPLAY_BLOCKED_RUNS')

    // Attach child logics to the scene logic so they persist across tab switches
    useAttachedLogic(batchJobsLogic, sceneLogic)
    useAttachedLogic(logic, sceneLogic)

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
            content: <Workflow {...workflowSceneProps} />,
        },

        {
            label: 'Invocations',
            key: 'logs',
            content: <WorkflowLogs id={workflowSceneProps.id!} />,
        },
        {
            label: 'Metrics',
            key: 'metrics',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <WorkflowMetrics id={workflowSceneProps.id!} />,
        },
        {
            label: 'History',
            key: 'history',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <ActivityLog id={workflowSceneProps.id!} scope={ActivityScope.HOG_FLOW} />,
        },
        showBlockedRuns
            ? {
                  label: 'Blocked runs',
                  key: 'blocked_runs' as WorkflowTab,
                  content: <BlockedRunsReplay id={workflowSceneProps.id!} />,
              }
            : null,
    ]

    return (
        <SceneContent className="h-full flex flex-col grow" data-attr="workflow-scene">
            <BindLogic logic={workflowLogic} props={{ id: props.id, tabId: props.tabId, templateId, editTemplateId }}>
                <WorkflowSceneHeader {...props} />
                <FlaggedFeature flag={FEATURE_FLAGS.WORKFLOWS_REPLAY_BLOCKED_RUNS}>
                    <BlockedRunsBanner id={props.id} />
                </FlaggedFeature>
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
            </BindLogic>
        </SceneContent>
    )
}
