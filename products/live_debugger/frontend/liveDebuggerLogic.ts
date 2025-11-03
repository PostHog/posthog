import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { liveDebuggerLogicType } from './liveDebuggerLogicType'

export interface Breakpoint {
    id: string
    repository: string | null
    filename: string
    line_number: number
    enabled: boolean
    condition?: string
    created_at: string
    updated_at: string
}

export interface BreakpointInstance {
    id: string
    lineNumber: number
    functionName?: string
    timestamp: string
    variables: Record<string, any>
    stackTrace?: any[]
    breakpoint_id?: string
    filename: string
}

export const liveDebuggerLogic = kea<liveDebuggerLogicType>([
    path(['products', 'live_debugger', 'frontend', 'liveDebuggerLogic']),

    actions({
        toggleBreakpoint: (filename: string, lineNumber: number, repository: string) => ({
            filename,
            lineNumber,
            repository,
        }),
        toggleBreakpointForFile: (filename: string, lineNumber: number, repository: string) => ({
            filename,
            lineNumber,
            repository,
        }),
        setHoveredLine: (lineNumber: number | null) => ({ lineNumber }),
        selectInstance: (instanceId: string | null) => ({ instanceId }),
        clearAllBreakpoints: true,
        markInstanceAsOld: (instanceId: string) => ({ instanceId }),
        showHitsForLine: (lineNumber: number | null) => ({ lineNumber }),
        startPollingBreakpoints: true,
        stopPollingBreakpoints: true,
        savePollingInterval: (intervalHdl: number) => ({ intervalHdl }),
        setSelectedFilePath: (filePath: string) => ({ filePath }),
        setCurrentRepository: (repository: string) => ({ repository }),
    }),

    loaders(({ values }) => ({
        breakpoints: [
            [] as Breakpoint[],
            {
                loadBreakpoints: async () => {
                    // Only load when both repository and file are selected
                    if (!values.currentRepository || !values.selectedFilePath) {
                        return []
                    }

                    const params = new URLSearchParams()
                    params.append('repository', values.currentRepository)
                    params.append('filename', values.selectedFilePath)

                    const queryString = params.toString()
                    const url = `api/projects/@current/live_debugger_breakpoints/?${queryString}`
                    const response = await api.get(url)
                    return response.results || []
                },
            },
        ],
        breakpointInstances: [
            [] as BreakpointInstance[],
            {
                loadBreakpointInstances: async () => {
                    // Filter hits by currently loaded breakpoints (for efficiency)
                    const breakpointIds = values.breakpoints.map((bp) => bp.id)

                    const params = new URLSearchParams()
                    breakpointIds.forEach((id: string) => params.append('breakpoint_ids', id))

                    const queryString = params.toString()
                    const url = `api/projects/@current/live_debugger_breakpoints/breakpoint_hits/${queryString ? `?${queryString}` : ''}`
                    const response = await api.get(url)
                    return response.results || []
                },
            },
        ],
    })),

    reducers({
        currentRepository: [
            'PostHog/posthog' as string,
            {
                setCurrentRepository: (_, { repository }) => repository,
            },
        ],
        selectedFilePath: [
            '',
            {
                setSelectedFilePath: (_, { filePath }) => filePath,
            },
        ],
        selectedInstanceId: [
            null as string | null,
            {
                selectInstance: (_, { instanceId }) => instanceId,
            },
        ],
        seenInstanceIds: [
            new Set<string>(),
            {
                markInstanceAsOld: (state, { instanceId }) => {
                    return new Set([...state, instanceId])
                },
                loadBreakpointInstancesSuccess: (state) => {
                    const newState = new Set(state)
                    return newState
                },
            },
        ],
        previousInstanceIds: [
            new Set<string>(),
            {
                loadBreakpointInstancesSuccess: (_, { breakpointInstances }) => {
                    return new Set(breakpointInstances.map((instance) => instance.id))
                },
            },
        ],
        selectedLineForHits: [
            null as number | null,
            {
                showHitsForLine: (_, { lineNumber }) => lineNumber,
            },
        ],
        breakpointPollingInterval: [
            null as number | null,
            {
                savePollingInterval: (_, { intervalHdl }) => intervalHdl,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadBreakpointInstancesSuccess: ({ breakpointInstances }) => {
            const newIds = breakpointInstances
                .map((instance) => instance.id)
                .filter((id) => !values.seenInstanceIds.has(id))

            if (newIds.length > 0) {
                setTimeout(() => {
                    newIds.forEach((id) => actions.markInstanceAsOld(id))
                }, 2000)
            }
        },
        toggleBreakpoint: async ({ filename, lineNumber, repository }) => {
            const existingBreakpoint = Array.isArray(values.breakpoints)
                ? values.breakpoints.find(
                      (bp) => bp.line_number === lineNumber && bp.filename === filename && bp.repository === repository
                  )
                : undefined

            if (existingBreakpoint) {
                await api.delete(`api/projects/@current/live_debugger_breakpoints/${existingBreakpoint.id}/`)
            } else {
                await api.create('api/projects/@current/live_debugger_breakpoints/', {
                    repository,
                    filename,
                    line_number: lineNumber,
                    enabled: true,
                })
            }

            actions.loadBreakpoints()
            actions.loadBreakpointInstances()
        },
        toggleBreakpointForFile: async ({ filename, lineNumber, repository }) => {
            const existingBreakpoint = Array.isArray(values.breakpoints)
                ? values.breakpoints.find(
                      (bp) => bp.line_number === lineNumber && bp.filename === filename && bp.repository === repository
                  )
                : undefined

            if (existingBreakpoint) {
                await api.delete(`api/projects/@current/live_debugger_breakpoints/${existingBreakpoint.id}/`)
            } else {
                await api.create('api/projects/@current/live_debugger_breakpoints/', {
                    repository,
                    filename,
                    line_number: lineNumber,
                    enabled: true,
                })
            }

            actions.loadBreakpoints()
            actions.loadBreakpointInstances()
        },
        clearAllBreakpoints: async () => {
            if (Array.isArray(values.breakpoints)) {
                await Promise.all(
                    values.breakpoints.map((bp) =>
                        api.delete(`api/projects/@current/live_debugger_breakpoints/${bp.id}/`)
                    )
                )
            }

            actions.loadBreakpoints()
            actions.loadBreakpointInstances()
        },
        startPollingBreakpoints: async () => {
            actions.loadBreakpoints()
            actions.loadBreakpointInstances()

            const interval = setInterval(() => {
                actions.loadBreakpoints()
                actions.loadBreakpointInstances()
            }, 15000)

            actions.savePollingInterval(interval as unknown as number)
        },
        stopPollingBreakpoints: () => {
            if (values.breakpointPollingInterval) {
                clearInterval(values.breakpointPollingInterval)
            }
        },
        setCurrentRepository: () => {
            // Reload breakpoints when repository changes (only if file is selected)
            if (values.selectedFilePath) {
                actions.loadBreakpoints()
            }
        },
        setSelectedFilePath: () => {
            // Reload breakpoints when file path changes (only if repository is set)
            if (values.currentRepository) {
                actions.loadBreakpoints()
            }
        },
        loadBreakpointsSuccess: () => {
            // Reload instances when breakpoints change (the list of IDs has changed)
            actions.loadBreakpointInstances()
        },
    })),

    selectors({
        selectedInstance: [
            (s) => [s.selectedInstanceId, s.breakpointInstances],
            (selectedId, instances): BreakpointInstance | null => instances.find((i) => i.id === selectedId) || null,
        ],
        visibleBreakpointIds: [
            (s) => [s.breakpoints],
            (breakpoints: Breakpoint[]): string[] => breakpoints.map((bp) => bp.id),
        ],
        breakpointLines: [
            (s) => [s.breakpoints, s.selectedFilePath],
            (breakpoints, selectedFilePath): number[] => {
                if (!Array.isArray(breakpoints) || !selectedFilePath) {
                    return []
                }
                return breakpoints
                    .filter((bp) => bp.filename === selectedFilePath)
                    .map((bp) => bp.line_number)
                    .sort((a, b) => a - b)
            },
        ],
        breakpointsByLine: [
            (s) => [s.breakpoints, s.selectedFilePath],
            (breakpoints, selectedFilePath): Record<number, Breakpoint> => {
                const byLine: Record<number, Breakpoint> = {}
                if (Array.isArray(breakpoints) && selectedFilePath) {
                    breakpoints
                        .filter((bp) => bp.filename === selectedFilePath)
                        .forEach((bp) => {
                            byLine[bp.line_number] = bp
                        })
                }
                return byLine
            },
        ],
        instancesByLine: [
            (s) => [s.breakpointInstances, s.selectedFilePath],
            (instances, selectedFilePath): Record<number, BreakpointInstance[]> => {
                const grouped: Record<number, BreakpointInstance[]> = {}
                instances
                    .filter((instance) => !selectedFilePath || instance.filename === selectedFilePath)
                    .forEach((instance) => {
                        if (!grouped[instance.lineNumber]) {
                            grouped[instance.lineNumber] = []
                        }
                        grouped[instance.lineNumber].push(instance)
                    })
                return grouped
            },
        ],
        newInstanceIds: [
            (s) => [s.breakpointInstances, s.seenInstanceIds],
            (instances, seenIds): Set<string> => {
                return new Set(instances.filter((instance) => !seenIds.has(instance.id)).map((instance) => instance.id))
            },
        ],
        hitCountsByLine: [
            (s) => [s.breakpointInstances, s.selectedFilePath],
            (instances, selectedFilePath): Record<number, number> => {
                const counts: Record<number, number> = {}
                instances
                    .filter((instance) => !selectedFilePath || instance.filename === selectedFilePath)
                    .forEach((instance) => {
                        counts[instance.lineNumber] = (counts[instance.lineNumber] || 0) + 1
                    })
                return counts
            },
        ],
        newHitsByLine: [
            (s) => [s.breakpointInstances, s.seenInstanceIds, s.selectedFilePath],
            (instances, seenIds, selectedFilePath): Set<number> => {
                const newInstances = instances
                    .filter((instance) => !seenIds.has(instance.id))
                    .filter((instance) => !selectedFilePath || instance.filename === selectedFilePath)
                return new Set(newInstances.map((instance) => instance.lineNumber))
            },
        ],
        hitsForSelectedLine: [
            (s) => [s.selectedLineForHits, s.instancesByLine],
            (selectedLine, instancesByLine): BreakpointInstance[] => {
                if (!selectedLine) {
                    return []
                }
                return instancesByLine[selectedLine] || []
            },
        ],
    }),

    events(({ actions }) => ({
        afterMount: [actions.startPollingBreakpoints],
        beforeUnmount: [actions.stopPollingBreakpoints],
    })),
])
