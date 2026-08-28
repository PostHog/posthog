import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

import { captureScoutFleetViewed } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_ROSTER_WINDOW_LABEL, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutAlphaBanner } from './ScoutAlphaBanner'
import { ScoutHelperSkillLinks } from './ScoutHelperSkillLinks'
import { ScoutsEmptyStateLegacy } from './ScoutsEmptyStateLegacy'
import { ScoutsRosterHeader } from './ScoutsRosterHeader'
import { ScoutsRosterTable } from './ScoutsRosterTable'

/**
 * Under this width the roster drops to its compact columns. Sits just above the ~763px the
 * six-column table needs before it starts scrolling sideways, so the switch happens where the wide
 * layout actually stops working rather than at a phone-sized guess. Measured on the roster itself
 * rather than the window, so the tab reads the same inside a narrow embed as it does on a phone.
 */
const ROSTER_COMPACT_MAX_PX = 768

/**
 * The scout roster with the redesign flag off: one alphabetical table over the whole troop, with lifecycle as a sortable
 * Status column. Replaces the card list that used to live in the Scout troop modal — the fleet
 * outgrew a 760px portal, and a modal can't host the scout pages it links to.
 */
export function ScoutsRosterLegacy(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, enabledCount, customScoutCount } = useValues(scoutFleetLogic)
    const { loadScoutConfigs, startRunsPolling, stopRunsPolling } = useActions(scoutFleetLogic)
    // One measurement for the whole roster, so the header chrome and the table agree on which
    // layout they're in — two observers could disagree for a frame mid-resize.
    const { ref: widthRef, size } = useResizeBreakpoints(
        { 0: 'compact', [ROSTER_COMPACT_MAX_PX]: 'wide' },
        { initialSize: 'wide' }
    )
    const compact = size === 'compact'

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
            <div className="flex flex-col gap-2 p-6">
                <LemonSkeleton className="h-8 w-full rounded" />
                <LemonSkeleton className="h-8 w-full rounded" />
                <LemonSkeleton className="h-8 w-full rounded" />
            </div>
        )
    }

    // A failed request must not masquerade as an empty troop – a missing scope or
    // regional rollout gap would otherwise be indistinguishable from "no scouts yet".
    if (scoutConfigs === null) {
        return (
            <div className="m-6 flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                <span className="flex-1 text-xs text-danger">
                    Couldn't load the scout roster. The scout API may be unavailable or this project may not be enrolled
                    yet.
                </span>
                <LemonButton type="secondary" size="small" status="danger" onClick={() => loadScoutConfigs()}>
                    Retry
                </LemonButton>
            </div>
        )
    }

    if (scoutConfigs.length === 0) {
        return <ScoutsEmptyStateLegacy />
    }

    return (
        <div ref={widthRef} className="flex flex-col">
            <ScoutAlphaBanner className="mx-6 mt-4" />
            <ScoutsRosterHeader compact={compact} />
            <ScoutsRosterTable compact={compact} />
            <div className="flex flex-col gap-1 px-6 py-4">
                <span className="text-xs text-muted">
                    The totals above cover the {SCOUT_ROSTER_WINDOW_LABEL}. Each scout's run strip shows its{' '}
                    {SCOUT_RUNS_PER_SCOUT_LABEL}, so scouts on different schedules stay comparable. New scouts are
                    created as <span className="font-mono text-[11px]">signals-scout-*</span> skills in your PostHog
                    project.
                </span>
                <ScoutHelperSkillLinks />
            </div>
        </div>
    )
}
