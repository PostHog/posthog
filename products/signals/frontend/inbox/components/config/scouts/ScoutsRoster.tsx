import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureScoutFleetViewed } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_ROSTER_WINDOW_LABEL, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { CardSkeleton } from '../../cards/CardSkeleton'
import { ScoutAlphaBanner } from './ScoutAlphaBanner'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutsEmptyState } from './ScoutsEmptyState'
import { ScoutsRosterFilters } from './ScoutsRosterFilters'
import { ScoutsRosterList } from './ScoutsRosterList'
import { ScoutsRosterStats } from './ScoutsRosterStats'

// The same centered column as the Reports tab, so the two tabs line up when switching between them.
const ROSTER_COLUMN_CLASS = '@container mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3'

/**
 * The scout roster: a toolbar (search, filters, sort on the left; the troop's headline numbers on
 * the right) over one column of scout cards, in the same layout as the report list. Creating a scout
 * stays in the scene header, so it is reachable even when the filters narrow the roster to nothing.
 */
export function ScoutsRoster(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, enabledCount, customScoutCount } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)

    useEffect(() => {
        startRunsPolling()
        return () => stopRunsPolling()
    }, [startRunsPolling, stopRunsPolling])

    // Roster shape once per opening, the first time the fleet resolves. A failed load stays `null`
    // and reports nothing — an unreachable scout API isn't an empty troop.
    const fleetViewedFiredRef = useRef(false)
    useEffect(() => {
        if (scoutConfigs === null || fleetViewedFiredRef.current) {
            return
        }
        fleetViewedFiredRef.current = true
        captureScoutFleetViewed({
            scoutCount: scoutConfigs.length,
            enabledCount,
            customCount: customScoutCount,
            dryRunCount: scoutConfigs.filter((config) => !config.emit).length,
        })
    }, [scoutConfigs, enabledCount, customScoutCount])

    if (scoutConfigsLoading && scoutConfigs === null) {
        return (
            <div className={ROSTER_COLUMN_CLASS}>
                <CardSkeleton count={3} variant="cards" dashed={false} />
            </div>
        )
    }

    // A failed request must not masquerade as an empty troop – a missing scope or
    // regional rollout gap would otherwise be indistinguishable from "no scouts yet".
    if (scoutConfigs === null) {
        return (
            <div className={ROSTER_COLUMN_CLASS}>
                <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                    <span className="flex-1 text-xs text-danger">
                        Couldn't load the scout roster. The scout API may be unavailable or this project may not be
                        enrolled yet.
                    </span>
                    <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutConfigs()}>
                        Retry
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (scoutConfigs.length === 0) {
        return (
            <div className={ROSTER_COLUMN_CLASS}>
                <ScoutsEmptyState />
            </div>
        )
    }

    return (
        <div className={ROSTER_COLUMN_CLASS}>
            <ScoutAlphaBanner />
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <ScoutsRosterFilters />
                <ScoutsRosterStats />
            </div>
            <ScoutsRosterList />
            <div className="flex flex-col gap-1 pt-1">
                <span className="text-xs text-muted">
                    The totals above cover the {SCOUT_ROSTER_WINDOW_LABEL}. Each scout's run strip shows its{' '}
                    {SCOUT_RUNS_PER_SCOUT_LABEL}, so scouts on different schedules stay comparable. New scouts are
                    created as <span className="font-mono text-[11px]">signals-scout-*</span> skills in your PostHog
                    project.{' '}
                    <Link to={urls.inboxRuns()} data-attr="inbox-open-runs">
                        See every recent run
                    </Link>
                </span>
                <ScoutHelperSkillLinks />
            </div>
        </div>
    )
}
