import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { liveDebuggerLogicType } from './liveDebuggerLogicType'

export interface Breakpoint {
    id: string
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
        toggleBreakpoint: (lineNumber: number) => ({ lineNumber }),
        toggleBreakpointForFile: (filename: string, lineNumber: number) => ({ filename, lineNumber }),
        setHoveredLine: (lineNumber: number | null) => ({ lineNumber }),
        selectInstance: (instanceId: string | null) => ({ instanceId }),
        clearAllBreakpoints: true,
        markInstanceAsOld: (instanceId: string) => ({ instanceId }),
        showHitsForLine: (lineNumber: number | null) => ({ lineNumber }),
        setExpandedFolderPaths: (paths: string[]) => ({ paths }),
    }),

    loaders(() => ({
        breakpoints: [
            [] as Breakpoint[],
            {
                loadBreakpoints: async () => {
                    const response = await api.get('api/environments/@current/live_debugger_breakpoints/')
                    return response.results || []
                },
            },
        ],
        breakpointInstances: [
            [] as BreakpointInstance[],
            {
                loadBreakpointInstances: async () => {
                    const response = await api.get(
                        'api/environments/@current/live_debugger_breakpoints/breakpoint_hits/'
                    )
                    return response.results || []
                },
            },
        ],
    })),

    reducers({
        selectedFilePath: [
            null as string | null,
            {
                selectFile: (_, { filePath }) => filePath,
            },
        ],
        expandedFolderPaths: [
            [] as string[],
            {
                setExpandedFolderPaths: (_, { paths }) => paths,
            },
        ],
        hoveredLine: [
            null as number | null,
            {
                setHoveredLine: (_, { lineNumber }) => lineNumber,
            },
        ],
        selectedInstanceId: [
            null as string | null,
            {
                selectInstance: (_, { instanceId }) => instanceId,
            },
        ],
        code: [
            '' as string,
            {
                loadCode: (_, { code }: { code: string }) => code,
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
        toggleBreakpoint: async ({ lineNumber }) => {
            const filename = values.selectedFilePath
            if (!filename) {
                console.warn('No file selected, cannot set breakpoint')
                return
            }

            const existingBreakpoint = Array.isArray(values.breakpoints)
                ? values.breakpoints.find((bp) => bp.line_number === lineNumber && bp.filename === filename)
                : undefined

            if (existingBreakpoint) {
                await api.delete(`api/environments/@current/live_debugger_breakpoints/${existingBreakpoint.id}/`)
            } else {
                await api.create('api/environments/@current/live_debugger_breakpoints/', {
                    filename,
                    line_number: lineNumber,
                    enabled: true,
                })
            }

            actions.loadBreakpoints()
            actions.loadBreakpointInstances()
        },
        toggleBreakpointForFile: async ({ filename, lineNumber }) => {
            const existingBreakpoint = Array.isArray(values.breakpoints)
                ? values.breakpoints.find((bp) => bp.line_number === lineNumber && bp.filename === filename)
                : undefined

            if (existingBreakpoint) {
                await api.delete(`api/environments/@current/live_debugger_breakpoints/${existingBreakpoint.id}/`)
            } else {
                await api.create('api/environments/@current/live_debugger_breakpoints/', {
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
                        api.delete(`api/environments/@current/live_debugger_breakpoints/${bp.id}/`)
                    )
                )
            }

            actions.loadBreakpoints()
            actions.loadBreakpointInstances()
        },
    })),

    selectors({
        selectedInstance: [
            (s) => [s.selectedInstanceId, s.breakpointInstances],
            (selectedId, instances): BreakpointInstance | null => instances.find((i) => i.id === selectedId) || null,
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
])
