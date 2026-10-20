import clsx from 'clsx'
import { useValues } from 'kea'

import { IconCheck, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import type { PanelImportOutcomeEnumApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsDashboardImportLogic } from '../metricsDashboardImportLogic'

const OUTCOMES: Record<PanelImportOutcomeEnumApi, { label: string; bar: string; icon: JSX.Element }> = {
    imported: { label: 'imported', bar: 'bg-success', icon: <IconCheck className="text-success" /> },
    approximated: { label: 'approximated', bar: 'bg-warning', icon: <IconWarning className="text-warning" /> },
    failed: { label: 'failed', bar: 'bg-danger', icon: <IconX className="text-danger" /> },
    skipped: { label: 'skipped', bar: 'bg-muted-alt', icon: <IconMinus className="text-muted" /> },
}
const OUTCOME_ORDER = Object.keys(OUTCOMES) as PanelImportOutcomeEnumApi[]

export function DashboardImportSummary(): JSX.Element | null {
    const { currentImport, sortedPanels } = useValues(metricsDashboardImportLogic)

    if (!currentImport) {
        return null
    }
    const { status, error, summary } = currentImport
    const counted = summary ? OUTCOME_ORDER.filter((outcome) => summary[outcome] > 0) : []

    return (
        <div className="flex flex-col gap-4">
            {status === 'failed' && <LemonBanner type="error">{error || 'The import failed. Try again.'}</LemonBanner>}
            {summary && summary.total > 0 && (
                <div className="flex flex-col gap-1.5">
                    <div className="flex h-2 gap-0.5 overflow-hidden rounded">
                        {counted.map((outcome) => (
                            <div
                                key={outcome}
                                className={OUTCOMES[outcome].bar}
                                // The width is the share of the panels with this outcome.
                                style={{ flexGrow: summary[outcome] }}
                            />
                        ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-secondary" translate="no">
                        {counted.map((outcome) => (
                            <span key={outcome} className="flex items-center gap-1">
                                <span className={clsx('size-2 rounded-full', OUTCOMES[outcome].bar)} />
                                {`${summary[outcome]} ${OUTCOMES[outcome].label}`}
                            </span>
                        ))}
                    </div>
                </div>
            )}
            {sortedPanels.length > 0 && (
                <ul className="m-0 p-0 list-none max-h-96 overflow-y-auto rounded border divide-y">
                    {sortedPanels.map((panel) => (
                        <li key={panel.key} className="flex gap-2 px-3 py-1.5 text-sm">
                            <span className="flex shrink-0 pt-0.5 text-base">{OUTCOMES[panel.outcome].icon}</span>
                            <div className="flex min-w-0 flex-col">
                                <span className={clsx('truncate', panel.outcome === 'skipped' && 'text-muted')}>
                                    {panel.title || 'Untitled'}
                                </span>
                                {panel.reason && <span className="text-xs text-secondary">{panel.reason}</span>}
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
