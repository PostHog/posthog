import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { Workflow } from './Workflow'
import {
    EMAIL_EDITOR_AGENT_HEADLINES,
    WORKFLOW_AGENT_HEADLINES,
    buildWorkflowAgentContext,
    isEditingEmailAction,
} from './workflowAgentContext'
import { WorkflowAssets } from './WorkflowAssets'
import { WorkflowInvocations } from './WorkflowInvocations'
import { workflowLogic } from './workflowLogic'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowRevisions } from './WorkflowRevisions'
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
    // The save/auto-save indicators moved into the WorkflowStatusBar; the scene only needs the
    // workflow itself (for the agent context) and the load state.
    const { workflow, workflowLoading, originalWorkflow, hogFunctionTemplatesById } = useValues(logic)

    // Attach child logics to the scene logic so they persist across tab switches
    useAttachedLogic(batchJobsLogic, sceneLogic)
    useAttachedLogic(logic, sceneLogic)

    // Debounced so per-keystroke edits don't re-serialize the whole graph into the agent context.
    // The id is debounced with the workflow as one value so a navigation between workflows can never
    // pair one workflow's ref with the other's editor state during the debounce window.
    const debouncedAgentSource = useDebouncedValue(
        useMemo(() => ({ workflow, id: workflowSceneProps.id ?? 'new' }), [workflow, workflowSceneProps.id]),
        500
    )
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    // The email takeover reflects its state into the URL (?editor=email beside the step's ?node=);
    // while it is open the panel's framing follows the email being edited, not the graph. Both
    // swaps update the same provider registrations in place, so they keep their first-registered
    // priority in the panel's first-writer-wins registries. Validated against the workflow's
    // actions, since a lingering param must not flip the framing on a workflow without that email.
    const editingEmail = isEditingEmailAction(workflow, searchParams)
    const editingEmailActionId: string | null = editingEmail ? ((searchParams.node as string) ?? null) : null
    // Serializing the whole graph is real work on large workflows, so skip building the context
    // entirely for users the integration flag hasn't reached.
    const agentContextItems = useMemo(
        () =>
            sceneIntegrationEnabled
                ? buildWorkflowAgentContext(
                      debouncedAgentSource.workflow,
                      debouncedAgentSource.id,
                      hogFunctionTemplatesById,
                      editingEmailActionId
                  )
                : null,
        [sceneIntegrationEnabled, debouncedAgentSource, hogFunctionTemplatesById, editingEmailActionId]
    )
    useSceneAgentPanel({
        sceneKey: 'workflow',
        contextItems: agentContextItems,
        headlines: editingEmail ? EMAIL_EDITOR_AGENT_HEADLINES : WORKFLOW_AGENT_HEADLINES,
        active: !!originalWorkflow || workflowSceneProps.id === 'new',
    })

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
            // Runtime view backed by hog_invocation_results, matching the hog function scene.
            // Old /logs deep links (and batchWorkflowJobsLogic) redirect here via workflowSceneLogic.
            label: 'Invocations',
            key: 'invocations',
            content: <WorkflowInvocations id={workflowSceneProps.id!} />,
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
            label: 'Assets',
            key: 'assets',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <WorkflowAssets id={workflowSceneProps.id!} />,
        },
        {
            label: 'History',
            key: 'history',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: (
                <div className="flex flex-col gap-6">
                    <WorkflowRevisions id={workflowSceneProps.id!} />
                    <div className="flex flex-col gap-2">
                        <h3 className="mb-0">Activity</h3>
                        <ActivityLog id={workflowSceneProps.id!} scope={ActivityScope.HOG_FLOW} />
                    </div>
                </div>
            ),
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
                        className={clsx({
                            'flex flex-col grow [&>div]:flex [&>div]:flex-col [&>div]:grow': currentTab === 'workflow',
                        })}
                    />
                )}
            </BindLogic>
        </SceneContent>
    )
}
