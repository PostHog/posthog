import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { blockedRunsLogicType } from './blockedRunsLogicType'

export interface BlockedRun {
    instance_id: string
    timestamp: string
    action_id: string | null
    event_uuid: string | null
    message: string
}

export interface BlockedRunsState {
    results: BlockedRun[]
    hasNext: boolean
    offset: number
}

export interface BlockedRunsLogicProps {
    id: string
}

const PAGE_SIZE = 100

const DEFAULT_BLOCKED_RUNS_STATE: BlockedRunsState = {
    results: [],
    hasNext: false,
    offset: 0,
}

export const blockedRunsLogic = kea<blockedRunsLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'blockedRunsLogic']),
    props({} as BlockedRunsLogicProps),
    key((props) => props.id),
    actions({
        toggleRunSelection: (instanceId: string) => ({ instanceId }),
        setSelectedRunIds: (ids: Set<string>) => ({ ids }),
        clearSelection: true,
        replaySelectedRuns: true,
        replayAllBlockedRuns: true,
        loadMoreBlockedRuns: true,
    }),
    loaders(({ props, values }) => ({
        blockedRuns: [
            DEFAULT_BLOCKED_RUNS_STATE,
            {
                loadBlockedRuns: async (): Promise<BlockedRunsState> => {
                    const response = await api.hogFlows.getBlockedRuns(props.id, PAGE_SIZE, 0)
                    return {
                        results: response.results,
                        hasNext: response.has_next,
                        offset: PAGE_SIZE,
                    }
                },
                loadMoreBlockedRuns: async (): Promise<BlockedRunsState> => {
                    const current = values.blockedRuns
                    const response = await api.hogFlows.getBlockedRuns(props.id, PAGE_SIZE, current.offset)
                    return {
                        results: [...current.results, ...response.results],
                        hasNext: response.has_next,
                        offset: current.offset + PAGE_SIZE,
                    }
                },
            },
        ],
    })),
    selectors({
        allBlockedRuns: [(s) => [s.blockedRuns], (blockedRuns) => blockedRuns.results],
        hasMoreRuns: [(s) => [s.blockedRuns], (blockedRuns) => blockedRuns.hasNext],
    }),
    reducers({
        selectedRunIds: [
            new Set<string>() as Set<string>,
            {
                toggleRunSelection: (state, { instanceId }) => {
                    const next = new Set(state)
                    if (next.has(instanceId)) {
                        next.delete(instanceId)
                    } else {
                        next.add(instanceId)
                    }
                    return next
                },
                setSelectedRunIds: (_, { ids }) => ids,
                clearSelection: () => new Set<string>(),
                loadBlockedRunsSuccess: () => new Set<string>(),
            },
        ],
        replayAllLoading: [
            false,
            {
                replayAllBlockedRuns: () => true,
                loadBlockedRunsSuccess: () => false,
                loadBlockedRunsFailure: () => false,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        replaySelectedRuns: async () => {
            const runs = values.allBlockedRuns.filter((r) => values.selectedRunIds.has(r.instance_id))
            const replayable = runs.filter((r) => r.event_uuid && r.action_id)

            if (replayable.length === 0) {
                lemonToast.warning('No replayable runs selected (missing event UUID or action ID)')
                return
            }

            let succeeded = 0
            let failed = 0

            for (const run of replayable) {
                try {
                    await api.hogFlows.replayBlockedRun(props.id, {
                        event_uuid: run.event_uuid!,
                        action_id: run.action_id!,
                        instance_id: run.instance_id,
                    })
                    succeeded++
                } catch {
                    failed++
                }
            }

            if (succeeded > 0) {
                lemonToast.success(`Queued ${succeeded} run${succeeded !== 1 ? 's' : ''} for replay`)
            }
            if (failed > 0) {
                lemonToast.error(`Failed to replay ${failed} run${failed !== 1 ? 's' : ''}`)
            }

            actions.loadBlockedRuns()
        },
        replayAllBlockedRuns: async () => {
            try {
                const result = await api.hogFlows.replayAllBlockedRuns(props.id)
                if (result.succeeded > 0) {
                    lemonToast.success(`Queued ${result.succeeded} run${result.succeeded !== 1 ? 's' : ''} for replay`)
                }
                if (result.failed > 0) {
                    lemonToast.error(`Failed to replay ${result.failed} run${result.failed !== 1 ? 's' : ''}`)
                }
                if (result.skipped > 0) {
                    lemonToast.warning(
                        `Skipped ${result.skipped} run${result.skipped !== 1 ? 's' : ''} (missing event or action data)`
                    )
                }
            } catch {
                lemonToast.error('Failed to replay blocked runs')
            }
            actions.loadBlockedRuns()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBlockedRuns()
    }),
])
