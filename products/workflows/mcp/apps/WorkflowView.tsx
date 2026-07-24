import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

import { STATUS_VARIANTS } from './utils'

export interface WorkflowData {
    id: string
    name: string
    description?: string | null
    status?: string
    version?: number
    trigger?: Record<string, unknown> | null
    exit_condition?: string | null
    created_at?: string
    updated_at?: string
    created_by?: { first_name?: string; email?: string } | null
    _posthogUrl?: string
}

export interface WorkflowViewProps {
    workflow: WorkflowData
}

export function WorkflowView({ workflow }: WorkflowViewProps): ReactElement {
    const status = workflow.status ?? 'draft'

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
                    </div>
                    {workflow.description && (
                        <span className="text-sm text-muted-foreground">{workflow.description}</span>
                    )}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(workflow.exit_condition
                                    ? [{ label: 'Exit condition', value: workflow.exit_condition }]
                                    : []),
                                ...(workflow.created_at
                                    ? [{ label: 'Created', value: formatDate(workflow.created_at) }]
                                    : []),
                                ...(workflow.updated_at
                                    ? [{ label: 'Updated', value: formatDate(workflow.updated_at) }]
                                    : []),
                                ...(workflow.created_by
                                    ? [
                                          {
                                              label: 'Created by',
                                              value:
                                                  workflow.created_by.first_name ||
                                                  workflow.created_by.email ||
                                                  'Unknown',
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                <div className="rounded-md border bg-muted/50 px-3 py-2">
                    <span className="text-xs text-muted-foreground">
                        View in PostHog for the full visual workflow editor
                    </span>
                </div>
            </div>
        </div>
    )
}
