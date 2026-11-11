import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

/**
 * How the commit's workflows ended, as counts. It names no verdict, because the repository's required checks are
 * not synced: a failed count can be an optional workflow, and a clean count can miss a required one.
 */
export function CIExplorerSummaryCounts(): JSX.Element {
    const { summary } = useValues(ciExplorerLogic)
    const counts: [number, string, string][] = [
        [summary.failed, 'failed', 'text-danger'],
        [summary.running, 'running', 'text-warning'],
        [summary.passed, 'passed', 'text-success'],
        [summary.other, 'cancelled or skipped', 'text-secondary'],
    ]
    return (
        <Tooltip title="Latest run of each workflow. Not a merge verdict: required checks are not synced.">
            <span className="flex flex-wrap gap-x-3 text-xs font-medium tabular-nums" data-attr="ci-explorer-summary">
                {counts
                    .filter(([count]) => count > 0)
                    .map(([count, label, className]) => (
                        <span key={label} className={className}>
                            {count} {label}
                        </span>
                    ))}
            </span>
        </Tooltip>
    )
}
