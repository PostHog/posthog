import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, formatDate, Stack } from '@posthog/mosaic'

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
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{workflow.name}</span>
                        <Badge variant={STATUS_VARIANTS[status] ?? 'neutral'} size="md">
                            {status.charAt(0).toUpperCase() + status.slice(1)}
                        </Badge>
                        {workflow.version != null && (
                            <Badge variant="neutral" size="sm">
                                v{workflow.version}
                            </Badge>
                        )}
                    </div>
                    {workflow.description && (
                        <span className="text-sm text-text-secondary">{workflow.description}</span>
                    )}
                </Stack>

                <Card padding="md">
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
                                              workflow.created_by.first_name || workflow.created_by.email || 'Unknown',
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </Card>

                <div className="rounded border border-border-primary bg-[var(--color-background-info)] px-3 py-2">
                    <span className="text-xs text-text-secondary">
                        View in PostHog for the full visual workflow editor
                    </span>
                </div>
            </Stack>
        </div>
    )
}
