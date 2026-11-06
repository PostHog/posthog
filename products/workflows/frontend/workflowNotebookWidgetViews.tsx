import { BindLogic, useActions, useValues } from 'kea'
import { lazy, Suspense, useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { WorkflowInvocations } from './Workflows/WorkflowInvocations'
import { workflowLogic } from './Workflows/workflowLogic'

const Workflow = lazy(() => import('./Workflows/Workflow').then((module) => ({ default: module.Workflow })))

export type WorkflowNotebookWidgetAttributes = {
    id: string
    view?: string
}

function WorkflowMetadata({ attributes }: NotebookNodeProps<WorkflowNotebookWidgetAttributes>): null {
    const { originalWorkflow } = useValues(workflowLogic({ id: attributes.id }))
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(originalWorkflow?.name || 'Workflow')
        setTitleStatus(
            originalWorkflow?.status
                ? {
                      label: capitalizeFirstLetter(originalWorkflow.status),
                      type: originalWorkflow.status === 'active' ? 'success' : 'default',
                  }
                : null
        )
    }, [originalWorkflow?.name, originalWorkflow?.status, setTitlePlaceholder, setTitleStatus])

    return null
}

function WorkflowLoading(): JSX.Element {
    return (
        <div className="p-3">
            <LemonSkeleton className="h-6 w-full" />
        </div>
    )
}

function WorkflowSummary({ attributes }: NotebookNodeProps<WorkflowNotebookWidgetAttributes>): JSX.Element {
    const { originalWorkflow, originalWorkflowLoading } = useValues(workflowLogic({ id: attributes.id }))

    if (!originalWorkflow && originalWorkflowLoading) {
        return <WorkflowLoading />
    }
    if (!originalWorkflow) {
        return <NotFound object="workflow" />
    }

    const actionCount = originalWorkflow.actions.filter(
        (action) => action.type !== 'trigger' && action.type !== 'exit'
    ).length
    const trigger = originalWorkflow.actions.find((action) => action.type === 'trigger')

    return (
        <>
            <WorkflowMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-wrap items-center gap-2 p-3">
                <span className="min-w-48 flex-1 truncate">{originalWorkflow.description || trigger?.description}</span>
                <LemonTag type="muted">
                    {actionCount} {actionCount === 1 ? 'step' : 'steps'}
                </LemonTag>
            </div>
        </>
    )
}

export function WorkflowDetail({ attributes }: NotebookNodeProps<WorkflowNotebookWidgetAttributes>): JSX.Element {
    const { originalWorkflow, originalWorkflowLoading } = useValues(workflowLogic({ id: attributes.id }))

    if (!originalWorkflow && originalWorkflowLoading) {
        return <WorkflowLoading />
    }
    if (!originalWorkflow) {
        return <NotFound object="workflow" />
    }

    return (
        <BindLogic logic={workflowLogic} props={{ id: attributes.id }}>
            <WorkflowMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-col gap-2 p-3">
                {originalWorkflow.actions.map((action, index) => (
                    <div className="flex items-start gap-3 rounded border p-3" key={action.id}>
                        <span className="text-secondary">{index + 1}</span>
                        <div className="min-w-0">
                            <div className="font-medium">{action.name}</div>
                            <div className="text-sm text-secondary">{action.description}</div>
                        </div>
                    </div>
                ))}
            </div>
        </BindLogic>
    )
}

function WorkflowEditor({ attributes }: NotebookNodeProps<WorkflowNotebookWidgetAttributes>): JSX.Element {
    return (
        <BindLogic logic={workflowLogic} props={{ id: attributes.id }}>
            <WorkflowMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex h-[40rem] p-3">
                <Suspense fallback={<WorkflowLoading />}>
                    <Workflow id={attributes.id} />
                </Suspense>
            </div>
        </BindLogic>
    )
}

function WorkflowResults({ attributes }: NotebookNodeProps<WorkflowNotebookWidgetAttributes>): JSX.Element {
    return (
        <BindLogic logic={workflowLogic} props={{ id: attributes.id }}>
            <WorkflowMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="max-h-[40rem] overflow-auto p-3">
                <WorkflowInvocations id={attributes.id} />
            </div>
        </BindLogic>
    )
}

export const WORKFLOW_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<WorkflowNotebookWidgetAttributes, 'Workflow'>(
    'Workflow',
    {
        summary: WorkflowSummary,
        editor: WorkflowEditor,
        results: WorkflowResults,
    }
)
