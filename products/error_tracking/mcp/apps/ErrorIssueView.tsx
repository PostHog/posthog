import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, formatDate, Link, Stack } from '@posthog/mosaic'

export interface ExternalIssue {
    external_url: string
    integration?: { display_name?: string }
}

export interface ErrorIssueData {
    id: string
    name: string
    description?: string | null
    status?: string
    first_seen?: string
    assignee?: { id: string; type: string } | null
    external_issues?: ExternalIssue[]
    _posthogUrl?: string
}

export interface ErrorIssueViewProps {
    issue: ErrorIssueData
}

const statusConfig: Record<string, { label: string; variant: 'success' | 'danger' | 'warning' | 'neutral' }> = {
    active: { label: 'Active', variant: 'danger' },
    resolved: { label: 'Resolved', variant: 'success' },
    archived: { label: 'Archived', variant: 'neutral' },
    pending_release: { label: 'Pending release', variant: 'warning' },
    suppressed: { label: 'Suppressed', variant: 'neutral' },
}

export function ErrorIssueView({ issue }: ErrorIssueViewProps): ReactElement {
    const cfg = statusConfig[issue.status ?? 'active'] ?? {
        label: issue.status ?? 'Unknown',
        variant: 'neutral' as const,
    }

    return (
        <div className="p-4">
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary break-all">{issue.name}</span>
                        <Badge variant={cfg.variant} size="md">
                            {cfg.label}
                        </Badge>
                    </div>
                    {issue.description && <span className="text-sm text-text-secondary">{issue.description}</span>}
                </Stack>

                <Card padding="md">
                    <DescriptionList
                        items={[
                            ...(issue.first_seen
                                ? [{ label: 'First seen', value: formatDate(issue.first_seen, true) }]
                                : []),
                            ...(issue.assignee
                                ? [{ label: 'Assignee', value: `${issue.assignee.type} (${issue.assignee.id})` }]
                                : []),
                        ]}
                    />
                </Card>

                {issue.external_issues && issue.external_issues.length > 0 && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">External issues</span>
                            {issue.external_issues.map((ext, i) => (
                                <div key={i} className="flex items-center gap-2">
                                    {ext.integration?.display_name && (
                                        <Badge variant="neutral" size="sm">
                                            {ext.integration.display_name}
                                        </Badge>
                                    )}
                                    <Link href={ext.external_url} external className="text-sm">
                                        {ext.external_url}
                                    </Link>
                                </div>
                            ))}
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
