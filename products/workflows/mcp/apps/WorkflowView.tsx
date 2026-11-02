import { type ReactElement, useEffect, useState } from 'react'

import { Badge } from '@posthog/quill'

import { WorkflowCanvasPreview } from 'products/workflows/frontend/Workflows/hogflows/editor/tile-canvas/preview/WorkflowCanvasPreview'

import type { HogFlowActionApi, HogFlowEdgeApi } from '../../frontend/generated/api.schemas'
import { useIsDarkTheme } from './useIsDarkTheme'
import { STATUS_VARIANTS } from './utils'

interface WorkflowSteps {
    exit_condition?: string | null
    actions?: HogFlowActionApi[]
    edges?: HogFlowEdgeApi[]
}

export interface WorkflowData extends WorkflowSteps {
    id: string
    name: string
    description?: string | null
    status?: string
    version?: number
    trigger?: Record<string, unknown> | null
    draft?: WorkflowSteps | null
    created_at?: string
    updated_at?: string
    created_by?: { first_name?: string; email?: string } | null
    _posthogUrl?: string
}

export interface WorkflowViewProps {
    workflow: WorkflowData
    loadFullWorkflow?: () => Promise<WorkflowData | null>
}

function lacksStepInputs(steps: WorkflowSteps): boolean {
    return !!steps.actions?.some(
        (action) => action.type.startsWith('function') && !(action.config as { inputs?: unknown }).inputs
    )
}

function useDrawnSteps(
    workflow: WorkflowData,
    loadFullWorkflow: WorkflowViewProps['loadFullWorkflow']
): WorkflowSteps | null {
    const given = workflow.draft ?? workflow
    const load = loadFullWorkflow && lacksStepInputs(given) ? loadFullWorkflow : undefined
    const [loaded, setLoaded] = useState<{ source: WorkflowData; full: WorkflowData | null } | null>(null)

    useEffect(() => {
        if (!load) {
            return
        }
        let current = true
        void load()
            .catch(() => null)
            .then((full) => current && setLoaded({ source: workflow, full }))
        return () => {
            current = false
        }
    }, [workflow, load])

    if (!load) {
        return given
    }
    if (loaded?.source !== workflow) {
        return null
    }
    return loaded.full ? (loaded.full.draft ?? loaded.full) : given
}

export function WorkflowView({ workflow, loadFullWorkflow }: WorkflowViewProps): ReactElement {
    const status = workflow.status ?? 'draft'
    const isDarkTheme = useIsDarkTheme()
    const steps = useDrawnSteps(workflow, loadFullWorkflow)

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{workflow.name}</span>
                        <Badge variant={STATUS_VARIANTS[status] ?? 'default'}>
                            {status.charAt(0).toUpperCase() + status.slice(1)}
                        </Badge>
                        {workflow.version != null && <Badge>v{workflow.version}</Badge>}
                        {workflow.draft && <Badge variant="warning">Unpublished changes</Badge>}
                    </div>
                    {workflow.description && (
                        <span className="text-sm text-muted-foreground">{workflow.description}</span>
                    )}
                </div>

                {!!steps?.actions?.length && (
                    <WorkflowCanvasPreview
                        actions={steps.actions}
                        edges={steps.edges ?? []}
                        exitCondition={steps.exit_condition}
                        isDarkModeOn={isDarkTheme}
                    />
                )}

                <div className="rounded-md border bg-muted/50 px-3 py-2">
                    <span className="text-xs text-muted-foreground">
                        View in PostHog for the full visual workflow editor
                    </span>
                </div>
            </div>
        </div>
    )
}
