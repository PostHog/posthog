import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch, Spinner, SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { NotFound } from 'lib/components/NotFound'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { Workflow } from './Workflow'
import { WorkflowInvocations } from './WorkflowInvocations'
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
    }
    const sceneLogic = workflowSceneLogic(workflowSceneProps)
    const { currentTab } = useValues(sceneLogic)
    const { searchParams } = useValues(router)
    const templateId = searchParams.templateId as string | undefined
    const editTemplateId = searchParams.editTemplateId as string | undefined

    const batchJobsLogic = batchWorkflowJobsLogic({ id: workflowSceneProps.id })

    const logic = workflowLogic({ id: props.id, templateId, editTemplateId })
    const { workflowLoading, originalWorkflow, lastSavedAt, isAutoSavePending, autoSaveEnabled } = useValues(logic)
    const { setAutoSaveEnabled } = useActions(logic)
    const showSaving = useDebouncedValue(isAutoSavePending || workflowLoading, 1000)
    const isDraft = originalWorkflow?.status === 'draft'

    const runsV2Enabled = useFeatureFlag('HOG_INVOCATION_RESULTS_RUNS_TAB')

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
            // Once the new Invocations (beta) tab is on, the old log viewer becomes "Logs"
            // to match the hog function scene and avoid two "Invocations" tabs.
            label: runsV2Enabled ? 'Logs' : 'Invocations',
            key: 'logs',
            content: <WorkflowLogs id={workflowSceneProps.id!} />,
        },
        runsV2Enabled
            ? {
                  label: (
                      <div className="flex flex-row">
                          <div>Invocations</div>
                          <LemonTag className="ml-2 uppercase" type="warning">
                              Beta
                          </LemonTag>
                      </div>
                  ),
                  key: 'invocations',
                  content: <WorkflowInvocations id={workflowSceneProps.id!} />,
              }
            : null,
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
    ]

    return (
        <SceneContent className="h-full flex flex-col grow" data-attr="workflow-scene">
            <BindLogic logic={workflowLogic} props={{ id: props.id, templateId, editTemplateId }}>
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
                        rightSlot={
                            isDraft ? (
                                <span className="flex items-center gap-3">
                                    {autoSaveEnabled && showSaving ? (
                                        <span className="text-xs text-tertiary flex items-center gap-1">
                                            <Spinner textColored /> Saving…
                                        </span>
                                    ) : lastSavedAt ? (
                                        <LastSavedIndicator timestamp={lastSavedAt} />
                                    ) : null}
                                    <span className="flex items-center gap-1">
                                        <LemonSwitch
                                            checked={autoSaveEnabled}
                                            onChange={setAutoSaveEnabled}
                                            label="Auto-save"
                                            size="small"
                                        />
                                        <Tooltip
                                            title="Auto-save is only available for draft workflows. Active workflows require an explicit save to prevent unintended changes to live behavior."
                                            placement="bottom"
                                        >
                                            <IconInfo className="text-tertiary size-4" />
                                        </Tooltip>
                                    </span>
                                </span>
                            ) : lastSavedAt ? (
                                <LastSavedIndicator timestamp={lastSavedAt} />
                            ) : null
                        }
                        className={clsx({
                            'flex flex-col grow [&>div]:flex [&>div]:flex-col [&>div]:grow': currentTab === 'workflow',
                        })}
                    />
                )}
            </BindLogic>
        </SceneContent>
    )
}
