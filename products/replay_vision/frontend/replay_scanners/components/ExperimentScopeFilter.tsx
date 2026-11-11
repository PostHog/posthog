import { useValues } from 'kea'

import { IconFlask } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { scannerExperimentScope, scopeVariantsLabel } from '../experimentTargeting'
import { replayScannerLogic } from '../replayScannerLogic'

export interface ExperimentScopeFilterProps {
    scannerId: string
}

/**
 * The experiment an experiment scanner watches, shown as the first condition of its recording filters.
 * The backend applies it at scan time, so it is not a filter the user can edit here.
 */
export function ExperimentScopeFilter({ scannerId }: ExperimentScopeFilterProps): JSX.Element | null {
    const { scanner, experimentContext } = useValues(replayScannerLogic({ id: scannerId }))
    const scope = scanner?.scanner_type === 'experiment' ? scannerExperimentScope(scanner) : null
    if (!scope) {
        return null
    }
    const experiment = experimentContext?.experiment.id === scope.experimentId ? experimentContext.experiment : null

    return (
        <div
            className="space-y-1.5 rounded border border-accent bg-accent-highlight-secondary p-3"
            data-attr="vision-experiment-scope-filter"
        >
            <div className="flex flex-wrap items-center gap-2">
                <IconFlask className="shrink-0 text-lg text-accent" />
                <span className="text-sm font-semibold">
                    People exposed to{' '}
                    {experiment ? (
                        <Link to={urls.experiment(scope.experimentId)}>{experiment.name}</Link>
                    ) : (
                        'this experiment'
                    )}
                </span>
                <LemonTag type="highlight">{scopeVariantsLabel(scope, 'every variant')}</LemonTag>
                <LemonTag type="muted">Always applied</LemonTag>
            </div>
            <div className="text-xs text-muted">
                This includes every session they have after their first exposure until the experiment ends, even
                sessions that never reach the part of the product the experiment changes. To scan only sessions that
                visit a certain page or flow, add a filter below, for example{' '}
                <strong className="text-default">Visited page</strong>.
            </div>
        </div>
    )
}
