import { MakeLogicType, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { visionScannersSelfDrivingStatsRetrieve } from '../generated/api'
import type { ScannerSelfDrivingStatsApi } from '../generated/api.schemas'

export interface ScannerSelfDrivingStatsLogicProps {
    scannerId: string
}

interface scannerSelfDrivingStatsLogicValues {
    selfDrivingStats: ScannerSelfDrivingStatsApi | null
    selfDrivingStatsLoading: boolean
}

interface scannerSelfDrivingStatsLogicActions {
    loadSelfDrivingStats: () => void
    loadSelfDrivingStatsSuccess: (selfDrivingStats: ScannerSelfDrivingStatsApi | null) => {
        selfDrivingStats: ScannerSelfDrivingStatsApi | null
    }
    loadSelfDrivingStatsFailure: (error: string) => { error: string }
}

export type scannerSelfDrivingStatsLogicType = MakeLogicType<
    scannerSelfDrivingStatsLogicValues,
    scannerSelfDrivingStatsLogicActions,
    ScannerSelfDrivingStatsLogicProps
>

// What self-driving did with this scanner's signals (reports contributed to, PRs opened). Shared by
// the Overview tab's Self-driving panel and the editor's self-driving toggle, hence its own logic.
// Null after a failed load, so both surfaces can tell "couldn't load" from "loaded zeros".
export const scannerSelfDrivingStatsLogic = kea<scannerSelfDrivingStatsLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerSelfDrivingStatsLogic']),
    props({} as ScannerSelfDrivingStatsLogicProps),
    key((props) => props.scannerId),
    loaders(({ props }) => ({
        selfDrivingStats: [
            null as ScannerSelfDrivingStatsApi | null,
            {
                loadSelfDrivingStats: async (): Promise<ScannerSelfDrivingStatsApi | null> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await visionScannersSelfDrivingStatsRetrieve(String(teamId), props.scannerId)
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadSelfDrivingStats()
    }),
])
