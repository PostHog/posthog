import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionActionsCreate, visionActionsRunsList, visionActionsRunsRetrieve } from '../generated/api'
import { VisionActionRunStatusEnumApi } from '../generated/api.schemas'
import type { VisionActionApi, VisionActionRunApi } from '../generated/api.schemas'
import type { scannerDigestLogicType } from './scannerDigestLogicType'
import { visionActionsLogic } from './visionActionsLogic'

export interface ScannerDigestLogicProps {
    scannerId: string
    scannerName: string
}

// Mirrors the backend default (digest.py); every morning at 8:00 in the team's timezone.
export const SCANNER_DIGEST_RRULE = 'FREQ=DAILY;BYHOUR=8;BYMINUTE=0'

// How many recent runs to scan for the newest completed one (skipped/failed runs don't carry a summary).
const RUN_LOOKBACK = 10

export const scannerDigestLogic = kea<scannerDigestLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerDigestLogic']),
    props({} as ScannerDigestLogicProps),
    key((props) => props.scannerId),

    connect((props: ScannerDigestLogicProps) => ({
        values: [visionActionsLogic({ scannerId: props.scannerId }), ['visionActions', 'visionActionsLoading']],
        actions: [
            visionActionsLogic({ scannerId: props.scannerId }),
            ['loadActions', 'loadActionsSuccess', 'toggleActionEnabled'],
        ],
    })),

    actions({
        loadLatestRun: true,
        loadLatestRunSuccess: (run: VisionActionRunApi | null) => ({ run }),
        loadLatestRunFailure: true,
        createDigest: true,
        createDigestSuccess: true,
        createDigestFailure: true,
        toggleExpanded: true,
    }),

    reducers({
        // The digest's newest completed run; kept while a refresh is in flight so the card doesn't flash.
        latestRun: [
            null as VisionActionRunApi | null,
            {
                loadLatestRunSuccess: (_, { run }) => run,
            },
        ],
        latestRunLoading: [
            true,
            {
                loadLatestRun: () => true,
                loadLatestRunSuccess: () => false,
                loadLatestRunFailure: () => false,
            },
        ],
        digestCreating: [
            false,
            {
                createDigest: () => true,
                createDigestSuccess: () => false,
                createDigestFailure: () => false,
            },
        ],
        expanded: [
            false,
            {
                toggleExpanded: (state) => !state,
            },
        ],
    }),

    selectors({
        digest: [
            (s) => [s.visionActions],
            (visionActions: VisionActionApi[]): VisionActionApi | null =>
                visionActions.find((a) => a.is_scanner_digest) ?? null,
        ],
    }),

    listeners(({ actions, props, values }) => ({
        loadActionsSuccess: () => {
            if (values.digest) {
                actions.loadLatestRun()
            } else {
                // No digest → nothing to fetch; clear the initial loading state so the opt-in card shows.
                actions.loadLatestRunSuccess(null)
            }
        },

        loadLatestRun: async (_, breakpoint) => {
            const teamId = teamLogic.values.currentTeamId
            const digest = values.digest
            if (!teamId || !digest) {
                actions.loadLatestRunFailure()
                return
            }
            try {
                const page = await visionActionsRunsList(String(teamId), digest.id, { limit: RUN_LOOKBACK })
                breakpoint()
                const completed = (page.results ?? []).find((r) => r.status === VisionActionRunStatusEnumApi.Completed)
                if (!completed) {
                    actions.loadLatestRunSuccess(null)
                    return
                }
                // The run list is deliberately light (no report body); fetch the full run for the markdown.
                const run = await visionActionsRunsRetrieve(String(teamId), digest.id, completed.id)
                breakpoint()
                actions.loadLatestRunSuccess(run)
            } catch {
                // Silent: the card falls back to the "first digest is on its way" state.
                actions.loadLatestRunFailure()
            }
        },

        createDigest: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.createDigestFailure()
                return
            }
            try {
                await visionActionsCreate(String(teamId), {
                    // Mirrors the backend provisioning defaults (digest.py) for scanners created before
                    // digests existed, or after the digest was deleted.
                    name: `Daily digest: ${props.scannerName}`.slice(0, 255),
                    scanner: props.scannerId,
                    is_scanner_digest: true,
                    trigger_config: {
                        rrule: SCANNER_DIGEST_RRULE,
                        timezone: teamLogic.values.currentTeam?.timezone || 'UTC',
                    },
                    delivery_config: [],
                })
                actions.createDigestSuccess()
                lemonToast.success('Daily digest turned on')
                actions.loadActions()
            } catch (error: any) {
                actions.createDigestFailure()
                lemonToast.error(`Couldn't turn on the daily digest${error?.detail ? `: ${error.detail}` : ''}`)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // visionActionsLogic loads on its own mount; if it already settled (tab was visited first),
        // loadActionsSuccess won't fire again, so resolve the card state here.
        if (!values.visionActionsLoading) {
            if (values.digest) {
                actions.loadLatestRun()
            } else {
                actions.loadLatestRunSuccess(null)
            }
        }
    }),
])
