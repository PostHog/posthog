import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import type { ScoringPreviewRowApi } from '../generated/api.schemas'
import { enrichmentScoringLogic } from './enrichmentScoringLogic'

export function EnrichmentScoringResults(): JSX.Element {
    const { preview, previewLoading, previewIsStale } = useValues(enrichmentScoringLogic)
    const columns: LemonTableColumns<ScoringPreviewRowApi> = [
        {
            title: 'Company',
            key: 'company',
            render: (_, row) => (
                <div className="min-w-0 break-words">
                    <div className="font-semibold">{row.company}</div>
                    <div className="text-secondary text-xs break-all">{row.domain ?? 'No domain'}</div>
                </div>
            ),
        },
        {
            title: 'Enrichments',
            key: 'enrichments',
            width: 120,
            render: (_, row) =>
                Object.keys(row.inputs.enrichments).length ? (
                    <div className="space-y-1 break-all text-xs" translate="no">
                        {Object.keys(row.inputs.enrichments).map((name) => (
                            <div key={name}>{name}</div>
                        ))}
                    </div>
                ) : (
                    <span className="text-secondary">None</span>
                ),
        },
        {
            title: 'Active',
            key: 'active',
            width: 80,
            align: 'right',
            render: (_, row) => row.active?.score ?? row.active?.status ?? 'Error',
        },
        {
            title: 'Preview',
            key: 'preview',
            width: 80,
            align: 'right',
            render: (_, row) => row.preview?.score ?? row.preview?.status ?? 'Error',
        },
        {
            title: 'Change',
            key: 'change',
            width: 80,
            align: 'right',
            render: (_, row) => {
                if (row.active?.score == null || row.preview?.score == null) {
                    return 'N/A'
                }
                const change = row.preview.score - row.active.score
                return <span className="tabular-nums">{change > 0 ? `+${change}` : change}</span>
            },
        },
    ]

    return (
        <div className="space-y-2">
            <h3 className="mb-0">Sample companies</h3>
            {previewIsStale && (
                <LemonBanner type="warning">
                    The selected configuration or formula has changed since this preview. Test it again to update these
                    results.
                </LemonBanner>
            )}
            {preview && (
                <p className="text-secondary text-sm mb-0">
                    {`${preview.response.summary.evaluated} companies evaluated · ${preview.response.summary.changed} changed · ${preview.response.summary.errors} errors`}
                </p>
            )}
            <LemonTable
                size="small"
                tableLayout="fixed"
                uppercaseHeader={false}
                dataSource={preview?.response.results ?? []}
                columns={columns}
                loading={previewLoading}
                rowKey={(row, index) => `${row.domain}-${index}`}
                emptyState={
                    preview
                        ? 'No saved company data is available to preview.'
                        : 'Test the formula to compare scores for 10 companies.'
                }
                expandable={{
                    expandedRowRender: (row) => (
                        <div className="space-y-3 min-w-0">
                            {row.error && <LemonBanner type="error">{row.error}</LemonBanner>}
                            <div>
                                <h4>Score details</h4>
                                <LemonTable
                                    size="small"
                                    tableLayout="fixed"
                                    rowKey="key"
                                    dataSource={[
                                        {
                                            key: 'status',
                                            name: 'Status',
                                            active: row.active?.status ?? 'Error',
                                            preview: row.preview?.status ?? 'Error',
                                        },
                                        {
                                            key: 'dq_reason',
                                            name: 'Disqualification reason',
                                            active: row.active?.dq_reason ?? null,
                                            preview: row.preview?.dq_reason ?? null,
                                        },
                                        ...Array.from(
                                            new Set([
                                                ...Object.keys(row.active?.components ?? {}),
                                                ...Object.keys(row.preview?.components ?? {}),
                                            ])
                                        ).map((name) => ({
                                            key: `component:${name}`,
                                            name,
                                            active: row.active?.components?.[name] ?? null,
                                            preview: row.preview?.components?.[name] ?? null,
                                        })),
                                        ...Array.from(
                                            new Set([
                                                ...Object.keys(row.active?.flags ?? {}),
                                                ...Object.keys(row.preview?.flags ?? {}),
                                            ])
                                        ).map((name) => ({
                                            key: `flag:${name}`,
                                            name: `Flag: ${name}`,
                                            active: row.active?.flags[name] ?? null,
                                            preview: row.preview?.flags[name] ?? null,
                                        })),
                                    ]}
                                    columns={[
                                        {
                                            title: 'Result',
                                            dataIndex: 'name',
                                            render: (_, detail) => <span className="break-all">{detail.name}</span>,
                                        },
                                        {
                                            title: 'Active',
                                            key: 'active',
                                            render: (_, component) => (
                                                <span className="break-words">
                                                    {String(component.active ?? 'None')}
                                                </span>
                                            ),
                                        },
                                        {
                                            title: 'Preview',
                                            key: 'preview',
                                            render: (_, component) => (
                                                <span className="break-words">
                                                    {String(component.preview ?? 'None')}
                                                </span>
                                            ),
                                        },
                                    ]}
                                    emptyState="No score details returned."
                                />
                            </div>
                            <div>
                                <h4>Draft inputs</h4>
                                <pre className="text-xs whitespace-pre-wrap break-all mb-0" translate="no">
                                    {JSON.stringify(row.inputs, null, 2)}
                                </pre>
                            </div>
                        </div>
                    ),
                }}
            />
        </div>
    )
}
