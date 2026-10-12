import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { PanelImportOutcomeEnumApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from '../metricsDashboardImportLogic'

const OUTCOMES: Record<PanelImportOutcomeEnumApi, { label: string; tagType: LemonTagType }> = {
    imported: { label: 'Imported', tagType: 'success' },
    approximated: { label: 'Approximated', tagType: 'warning' },
    failed: { label: 'Failed', tagType: 'danger' },
    skipped: { label: 'Skipped', tagType: 'muted' },
}

export function DashboardImportSummary(): JSX.Element | null {
    const { currentImport, sortedPanels } = useValues(metricsDashboardImportLogic)

    if (!currentImport) {
        return null
    }
    const { status, error, summary, dashboard_name } = currentImport

    return (
        <div className="@container/import-summary flex flex-col gap-4">
            {status === 'failed' ? (
                <LemonBanner type="error">{error || 'The import failed. Try again.'}</LemonBanner>
            ) : summary ? (
                <p className="m-0">
                    {`${summary.imported + summary.approximated} of ${summary.total} panels are on the dashboard "${dashboard_name}".`}
                </p>
            ) : null}
            {summary && (
                <div className="grid grid-cols-2 gap-2 @min-[32rem]/import-summary:grid-cols-4">
                    {(Object.keys(OUTCOMES) as PanelImportOutcomeEnumApi[]).map((outcome) => (
                        <div key={outcome} className="rounded border p-2">
                            <div className="text-xs text-secondary">{OUTCOMES[outcome].label}</div>
                            <div className="text-xl font-semibold" translate="no">
                                {summary[outcome]}
                            </div>
                        </div>
                    ))}
                </div>
            )}
            {!!summary?.approximated && (
                <p className="m-0 text-secondary">
                    Approximated panels are on the dashboard, but they show different data. The details say what
                    changed.
                </p>
            )}
            {sortedPanels.length > 0 && (
                <LemonTable
                    dataSource={sortedPanels}
                    rowKey="key"
                    size="small"
                    columns={[
                        {
                            title: 'Panel',
                            key: 'title',
                            render: (_, panel) => panel.title || <span className="text-secondary">Untitled</span>,
                        },
                        {
                            title: 'Result',
                            key: 'outcome',
                            render: (_, panel) => (
                                <LemonTag type={OUTCOMES[panel.outcome].tagType}>
                                    {OUTCOMES[panel.outcome].label}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Details',
                            key: 'reason',
                            render: (_, panel) => panel.reason,
                        },
                    ]}
                />
            )}
        </div>
    )
}
