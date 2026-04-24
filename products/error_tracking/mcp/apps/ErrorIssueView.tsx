import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, formatDate, Link, Stack } from '@posthog/mosaic'

export interface ExternalIssue {
    external_url: string
    integration?: { display_name?: string }
}

export interface ErrorIssueImpact {
    occurrences?: number
    users?: number
    sessions?: number
}

export interface ErrorIssueCulprit {
    function?: string
    source?: string
    line?: number
    column?: number
    in_app?: boolean
}

export interface ErrorIssueRelease {
    version?: string
    project?: string
    timestamp?: string
    commit_id?: string
    branch?: string
    repo_name?: string
}

export interface ErrorIssueData {
    id: string
    name: string
    description?: string | null
    status?: string
    first_seen?: string
    last_seen?: string
    library?: string
    source?: string
    function?: string
    impact?: ErrorIssueImpact
    culprit?: ErrorIssueCulprit
    latest_release?: ErrorIssueRelease
    sparkline?: number[]
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

function hasValues(record: object | undefined): boolean {
    return !!record && Object.values(record).some((value) => value !== undefined && value !== null && value !== '')
}

function CompactSparkline({ values }: { values: number[] }): ReactElement | null {
    if (!values.length) {
        return null
    }

    const max = Math.max(...values, 1)
    return (
        <div className="flex h-8 items-end gap-0.5">
            {values.map((value, index) => (
                <div
                    key={index}
                    className="w-1.5 rounded-sm bg-danger"
                    style={{ height: `${Math.max((value / max) * 100, value > 0 ? 12 : 4)}%` }}
                    title={String(value)}
                />
            ))}
        </div>
    )
}

export function ErrorIssueView({ issue }: ErrorIssueViewProps): ReactElement {
    const cfg = statusConfig[issue.status ?? 'active'] ?? {
        label: issue.status ?? 'Unknown',
        variant: 'neutral' as const,
    }
    const impact = issue.impact
    const culprit = issue.culprit
    const latestRelease = issue.latest_release

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
                            ...(issue.last_seen
                                ? [{ label: 'Last seen', value: formatDate(issue.last_seen, true) }]
                                : []),
                            ...(issue.library ? [{ label: 'Library', value: issue.library }] : []),
                            ...(issue.assignee
                                ? [{ label: 'Assignee', value: `${issue.assignee.type} (${issue.assignee.id})` }]
                                : []),
                        ]}
                    />
                </Card>

                {(hasValues(impact) || issue.sparkline?.length) && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <DescriptionList
                                columns={2}
                                items={[
                                    ...(impact?.occurrences !== undefined
                                        ? [{ label: 'Occurrences', value: impact.occurrences.toLocaleString() }]
                                        : []),
                                    ...(impact?.users !== undefined
                                        ? [{ label: 'Users', value: impact.users.toLocaleString() }]
                                        : []),
                                    ...(impact?.sessions !== undefined
                                        ? [{ label: 'Sessions', value: impact.sessions.toLocaleString() }]
                                        : []),
                                ]}
                            />
                            {issue.sparkline && <CompactSparkline values={issue.sparkline} />}
                        </Stack>
                    </Card>
                )}

                {(hasValues(culprit) || hasValues(latestRelease)) && (
                    <Card padding="md">
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(culprit?.function ? [{ label: 'Function', value: culprit.function }] : []),
                                ...(culprit?.source
                                    ? [
                                          {
                                              label: 'Source',
                                              value: `${culprit.source}${culprit.line ? `:${culprit.line}` : ''}${culprit.column ? `:${culprit.column}` : ''}`,
                                          },
                                      ]
                                    : []),
                                ...(latestRelease?.version ? [{ label: 'Release', value: latestRelease.version }] : []),
                                ...(latestRelease?.project ? [{ label: 'Project', value: latestRelease.project }] : []),
                                ...(latestRelease?.commit_id
                                    ? [{ label: 'Commit', value: latestRelease.commit_id.slice(0, 12) }]
                                    : []),
                                ...(latestRelease?.branch ? [{ label: 'Branch', value: latestRelease.branch }] : []),
                            ]}
                        />
                    </Card>
                )}

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
