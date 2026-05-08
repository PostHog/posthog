import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Button, Card, CardContent } from '@posthog/quill'

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

const statusConfig: Record<string, { label: string; variant: 'success' | 'destructive' | 'warning' | 'default' }> = {
    active: { label: 'Active', variant: 'destructive' },
    resolved: { label: 'Resolved', variant: 'success' },
    archived: { label: 'Archived', variant: 'default' },
    pending_release: { label: 'Pending release', variant: 'warning' },
    suppressed: { label: 'Suppressed', variant: 'default' },
}

export function ErrorIssueView({ issue }: ErrorIssueViewProps): ReactElement {
    const cfg = statusConfig[issue.status ?? 'active'] ?? {
        label: issue.status ?? 'Unknown',
        variant: 'default' as const,
    }

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold break-all">{issue.name}</span>
                        <Badge variant={cfg.variant}>{cfg.label}</Badge>
                    </div>
                    {issue.description && <span className="text-sm text-muted-foreground">{issue.description}</span>}
                </div>

                <Card>
                    <CardContent>
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
                    </CardContent>
                </Card>

                {issue.external_issues && issue.external_issues.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-2">
                                <span className="text-sm font-semibold">External issues</span>
                                {issue.external_issues.map((ext, i) => (
                                    <div key={i} className="flex items-center gap-2">
                                        {ext.integration?.display_name && <Badge>{ext.integration.display_name}</Badge>}
                                        <Button
                                            variant="link"
                                            size="sm"
                                            // eslint-disable-next-line react/forbid-elements
                                            render={<a href={ext.external_url} target="_blank" rel="noreferrer" />}
                                        >
                                            {ext.external_url}
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
