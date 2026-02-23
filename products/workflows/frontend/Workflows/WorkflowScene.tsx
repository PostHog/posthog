import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock } from '@posthog/icons'
import { LemonBanner, LemonCollapse, SpinnerOverlay } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { batchWorkflowJobsLogic } from './batchWorkflowJobsLogic'
import { Workflow } from './Workflow'
import { workflowLogic } from './workflowLogic'
import { WorkflowLogs } from './WorkflowLogs'
import { WorkflowMetrics } from './WorkflowMetrics'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'
import { WorkflowSceneLogicProps, WorkflowTab, workflowSceneLogic } from './workflowSceneLogic'

function formatDateTime(isoString: string): string {
    return new Date(isoString).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    })
}

function DraftChangesSummary({
    summary,
}: {
    summary: { added: string[]; modified: string[]; deleted: string[] }
}): JSX.Element | null {
    const { added, modified, deleted } = summary
    const totalChanges = added.length + modified.length + deleted.length
    if (totalChanges === 0) {
        return null
    }

    const panels = [
        {
            key: 'changes',
            header: `${totalChanges} action${totalChanges === 1 ? '' : 's'} changed`,
            content: (
                <ul className="list-none p-0 m-0 space-y-0.5">
                    {added.map((name) => (
                        <li key={`add-${name}`} className="text-success font-medium">
                            + {name}
                        </li>
                    ))}
                    {modified.map((name) => (
                        <li key={`mod-${name}`} className="text-warning font-medium">
                            ~ {name}
                        </li>
                    ))}
                    {deleted.map((name) => (
                        <li key={`del-${name}`} className="text-danger font-medium">
                            &minus; {name}
                        </li>
                    ))}
                </ul>
            ),
        },
    ]

    return <LemonCollapse panels={panels} size="xsmall" className="mt-1" />
}

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
    const sceneLogic = workflowSceneLogic(props)
    const { currentTab } = useValues(sceneLogic)
    const { searchParams } = useValues(router)
    const templateId = searchParams.templateId as string | undefined
    const editTemplateId = searchParams.editTemplateId as string | undefined

    const batchJobsLogic = batchWorkflowJobsLogic({ id: props.id })
    const { futureJobs } = useValues(batchJobsLogic)

    const logic = workflowLogic({ id: props.id, tabId: props.tabId, templateId, editTemplateId })
    const { workflowLoading, originalWorkflow, hasPendingDraft, isDraftSaving, draftSavedAt, draftChangesSummary } =
        useValues(logic)

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
            <BindLogic logic={workflowLogic} props={{ id: props.id, tabId: props.tabId, templateId, editTemplateId }}>
                <WorkflowSceneHeader {...props} />
                {hasPendingDraft && originalWorkflow.status === 'active' && (
                    <LemonBanner type="info" className="mx-4 mt-2">
                        <div>
                            Unpublished changes.
                            {isDraftSaving
                                ? ' Saving...'
                                : draftSavedAt
                                  ? ` Last autosaved ${formatDateTime(draftSavedAt)}.`
                                  : ''}
                        </div>
                        <DraftChangesSummary summary={draftChangesSummary} />
                    </LemonBanner>
                )}
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
