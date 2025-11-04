import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import type { Breakpoint, BreakpointInstance } from './liveDebuggerLogic'
import { liveDebuggerLogic } from './liveDebuggerLogic'

jest.mock('lib/api')

describe('liveDebuggerLogic', () => {
    let logic: ReturnType<typeof liveDebuggerLogic.build>

    // Mock data
    const mockBreakpoints: Breakpoint[] = [
        {
            id: 'bp-1',
            repository: 'PostHog/posthog',
            filename: 'capture_event.py',
            line_number: 100,
            enabled: true,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
        },
        {
            id: 'bp-2',
            repository: 'PostHog/posthog',
            filename: 'capture_event.py',
            line_number: 200,
            enabled: true,
            condition: 'user_id == "test"',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
        },
        {
            id: 'bp-3',
            repository: 'PostHog/frontend',
            filename: 'capture_event.py',
            line_number: 100,
            enabled: true,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
        },
    ]

    const mockInstances: BreakpointInstance[] = [
        {
            id: 'inst-1',
            lineNumber: 100,
            filename: 'capture_event.py',
            timestamp: '2024-01-01T10:00:00Z',
            variables: { user_id: 'user-123', event: 'pageview' },
            breakpoint_id: 'bp-1',
        },
        {
            id: 'inst-2',
            lineNumber: 200,
            filename: 'capture_event.py',
            timestamp: '2024-01-01T10:01:00Z',
            variables: { user_id: 'user-456', event: 'click' },
            breakpoint_id: 'bp-2',
        },
    ]

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.clearAllMocks()
    })

    describe('initialization', () => {
        it('mounts successfully with default values', async () => {
            logic = liveDebuggerLogic()
            logic.mount()

            // Wait for initial load actions (they won't fetch data without a selected file)
            await expectLogic(logic).toDispatchActions(['startPollingBreakpoints'])

            expect(logic.values).toMatchObject({
                currentRepository: 'PostHog/posthog',
                selectedFilePath: '',
                selectedInstanceId: null,
                selectedLineForHits: null,
                breakpoints: [],
                breakpointInstances: [],
            })
        })

        it('starts polling on mount and loads data when file is selected', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['startPollingBreakpoints'])

            // Select a file to trigger data loading
            logic.actions.setSelectedFilePath('test.py')

            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess', 'loadBreakpointInstancesSuccess'])

            expect(api.get).toHaveBeenCalledWith(
                'api/projects/@current/live_debugger_breakpoints/?repository=PostHog%2Fposthog&filename=test.py'
            )
        })

        it('stops polling on unmount', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            const clearIntervalSpy = jest.spyOn(global, 'clearInterval')

            logic = liveDebuggerLogic()
            logic.mount()

            // Wait for polling to start
            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            const intervalId = logic.values.breakpointPollingInterval
            expect(intervalId).not.toBeNull()

            // Stop polling (this is what beforeUnmount does)
            await expectLogic(logic, () => {
                logic.actions.stopPollingBreakpoints()
            }).toDispatchActions(['stopPollingBreakpoints'])

            expect(clearIntervalSpy).toHaveBeenCalledWith(intervalId)
        })
    })

    describe('loaders', () => {
        it('loads breakpoints from API when repository and file are set', async () => {
            // Mock both breakpoints and instances loading
            const mockGet = jest.spyOn(api, 'get')
            mockGet.mockImplementation((url: string) => {
                if (url.includes('breakpoint_hits')) {
                    // Return empty hits
                    return Promise.resolve({ results: [], count: 0, has_more: false })
                }
                // Return breakpoints
                return Promise.resolve({ results: mockBreakpoints, count: mockBreakpoints.length, has_more: false })
            })

            logic = liveDebuggerLogic()
            logic.mount()

            // Wait for mount to complete (first loadBreakpoints that returns [])
            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            // Now set file path - the listener will automatically call loadBreakpoints
            await expectLogic(logic, () => {
                logic.actions.setSelectedFilePath('capture_event.py')
            })
                .toDispatchActions(['setSelectedFilePath', 'loadBreakpoints', 'loadBreakpointsSuccess'])
                .toMatchValues({
                    breakpoints: mockBreakpoints,
                    breakpointsLoading: false,
                })
        })

        it('loads breakpoint instances from API with filtered breakpoint IDs', async () => {
            // Mock for loading breakpoints (returns breakpoints with IDs)
            const mockGet = jest.spyOn(api, 'get')
            mockGet.mockImplementation((url: string) => {
                if (url.includes('live_debugger_breakpoints/breakpoint_hits')) {
                    return Promise.resolve({ results: mockInstances, count: mockInstances.length, has_more: false })
                }
                return Promise.resolve({ results: mockBreakpoints, count: mockBreakpoints.length, has_more: false })
            })

            logic = liveDebuggerLogic()
            logic.mount()

            logic.actions.setSelectedFilePath('capture_event.py')

            // Wait for both breakpoints and instances to load
            await expectLogic(logic)
                .toDispatchActions(['loadBreakpointsSuccess', 'loadBreakpointInstancesSuccess'])
                .toMatchValues({
                    breakpointInstances: mockInstances,
                    breakpointInstancesLoading: false,
                })

            // Should be called with breakpoint IDs from loaded breakpoints
            expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('breakpoint_hits/?breakpoint_ids='))
        })

        it('handles missing results field in API response', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            logic.actions.setSelectedFilePath('test.py')

            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess']).toMatchValues({
                breakpoints: [],
            })
        })
    })

    describe('toggle breakpoint', () => {
        it('creates a new breakpoint when it does not exist', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            jest.spyOn(api, 'create').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('test.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.toggleBreakpoint('test.py', 50, 'PostHog/posthog')
            }).toDispatchActions(['toggleBreakpoint', 'loadBreakpoints', 'loadBreakpointInstances'])

            expect(api.create).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/', {
                repository: 'PostHog/posthog',
                filename: 'test.py',
                line_number: 50,
                enabled: true,
            })
        })

        it('deletes an existing breakpoint when it exists', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockBreakpoints,
                count: mockBreakpoints.length,
                has_more: false,
            })
            jest.spyOn(api, 'delete').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('capture_event.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.toggleBreakpoint('capture_event.py', 100, 'PostHog/posthog')
            }).toDispatchActions(['toggleBreakpoint'])

            expect(api.delete).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/bp-1/')
        })

        it('only deletes breakpoint with matching repository', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockBreakpoints,
                count: mockBreakpoints.length,
                has_more: false,
            })
            jest.spyOn(api, 'create').mockResolvedValue({})
            jest.spyOn(api, 'delete').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('capture_event.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            // Same file/line but different repository - should create, not delete
            await expectLogic(logic, () => {
                logic.actions.toggleBreakpoint('capture_event.py', 100, 'PostHog/backend')
            }).toDispatchActions(['toggleBreakpoint'])

            expect(api.delete).not.toHaveBeenCalled()
            expect(api.create).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/', {
                repository: 'PostHog/backend',
                filename: 'capture_event.py',
                line_number: 100,
                enabled: true,
            })
        })

        it('toggleBreakpointForFile works the same as toggleBreakpoint', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            jest.spyOn(api, 'create').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('test.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.toggleBreakpointForFile('test.py', 50, 'PostHog/posthog')
            }).toDispatchActions(['toggleBreakpointForFile', 'loadBreakpoints', 'loadBreakpointInstances'])

            expect(api.create).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/', {
                repository: 'PostHog/posthog',
                filename: 'test.py',
                line_number: 50,
                enabled: true,
            })
        })
    })

    describe('clear all breakpoints', () => {
        it('deletes all breakpoints via Promise.all', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockBreakpoints,
                count: mockBreakpoints.length,
                has_more: false,
            })
            jest.spyOn(api, 'delete').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('capture_event.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.clearAllBreakpoints()
            }).toDispatchActions(['clearAllBreakpoints', 'loadBreakpoints', 'loadBreakpointInstances'])

            expect(api.delete).toHaveBeenCalledTimes(3)
            expect(api.delete).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/bp-1/')
            expect(api.delete).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/bp-2/')
            expect(api.delete).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/bp-3/')
        })

        it('handles empty breakpoints array gracefully', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            jest.spyOn(api, 'delete').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints (empty result)
            logic.actions.setSelectedFilePath('test.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.clearAllBreakpoints()
            }).toDispatchActions(['clearAllBreakpoints'])

            expect(api.delete).not.toHaveBeenCalled()
        })
    })

    describe('polling', () => {
        it('startPollingBreakpoints loads data immediately and sets up interval', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            const setIntervalSpy = jest.spyOn(global, 'setInterval')

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions([
                'startPollingBreakpoints',
                'loadBreakpoints',
                'loadBreakpointInstances',
            ])

            expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 15000)
            expect(logic.values.breakpointPollingInterval).toBeTruthy()
        })

        it('polling interval loads data every 15 seconds', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            // Initial load
            expect(api.get).toHaveBeenCalledTimes(2)

            // Advance 15 seconds
            jest.advanceTimersByTime(15000)
            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            // Should have called 2 more times (breakpoints + instances)
            expect(api.get).toHaveBeenCalledTimes(4)

            // Advance another 15 seconds
            jest.advanceTimersByTime(15000)
            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            expect(api.get).toHaveBeenCalledTimes(6)
        })

        it('stopPollingBreakpoints clears the interval', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            const clearIntervalSpy = jest.spyOn(global, 'clearInterval')

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadBreakpoints'])

            const intervalId = logic.values.breakpointPollingInterval

            logic.actions.stopPollingBreakpoints()

            expect(clearIntervalSpy).toHaveBeenCalledWith(intervalId)
        })
    })

    describe('instance tracking', () => {
        it('markInstanceAsOld adds instance ID to seenInstanceIds', () => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })

            logic = liveDebuggerLogic()
            logic.mount()

            logic.actions.markInstanceAsOld('inst-1')

            expect(logic.values.seenInstanceIds.has('inst-1')).toBe(true)
        })

        it('loadBreakpointInstancesSuccess auto-marks new instances as old after 2s', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockInstances,
                count: mockInstances.length,
                has_more: false,
            })

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadBreakpointInstancesSuccess'])

            // Initially not marked as old
            expect(logic.values.seenInstanceIds.has('inst-1')).toBe(false)
            expect(logic.values.seenInstanceIds.has('inst-2')).toBe(false)

            // Advance 2 seconds
            jest.advanceTimersByTime(2000)

            // Now should be marked as old
            expect(logic.values.seenInstanceIds.has('inst-1')).toBe(true)
            expect(logic.values.seenInstanceIds.has('inst-2')).toBe(true)
        })

        it('updates previousInstanceIds on load', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockInstances,
                count: mockInstances.length,
                has_more: false,
            })

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadBreakpointInstancesSuccess'])

            expect(logic.values.previousInstanceIds.has('inst-1')).toBe(true)
            expect(logic.values.previousInstanceIds.has('inst-2')).toBe(true)
        })

        it('only auto-marks new instances not already in seenInstanceIds', async () => {
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockInstances,
                count: mockInstances.length,
                has_more: false,
            })

            logic = liveDebuggerLogic()
            logic.mount()

            // Mark inst-1 as already seen
            logic.actions.markInstanceAsOld('inst-1')

            await expectLogic(logic).toDispatchActions(['loadBreakpointInstancesSuccess'])

            // Advance 2 seconds
            jest.advanceTimersByTime(2000)

            // inst-1 was already seen, inst-2 is new
            expect(logic.values.seenInstanceIds.has('inst-1')).toBe(true)
            expect(logic.values.seenInstanceIds.has('inst-2')).toBe(true)
        })
    })

    describe('reducers', () => {
        beforeEach(() => {
            jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0, has_more: false })
            logic = liveDebuggerLogic()
            logic.mount()
        })

        it('setCurrentRepository updates repository state', () => {
            logic.actions.setCurrentRepository('PostHog/frontend')

            expect(logic.values.currentRepository).toBe('PostHog/frontend')
        })

        it('setSelectedFilePath updates file selection', () => {
            logic.actions.setSelectedFilePath('capture_event.py')

            expect(logic.values.selectedFilePath).toBe('capture_event.py')
        })

        it('selectInstance updates selected instance ID', () => {
            logic.actions.selectInstance('inst-1')

            expect(logic.values.selectedInstanceId).toBe('inst-1')

            logic.actions.selectInstance(null)

            expect(logic.values.selectedInstanceId).toBe(null)
        })

        it('showHitsForLine updates selected line', () => {
            logic.actions.showHitsForLine(100)

            expect(logic.values.selectedLineForHits).toBe(100)

            logic.actions.showHitsForLine(null)

            expect(logic.values.selectedLineForHits).toBe(null)
        })

        it('savePollingInterval updates interval ID', () => {
            const intervalId = 12345 as unknown as number

            logic.actions.savePollingInterval(intervalId)

            expect(logic.values.breakpointPollingInterval).toBe(intervalId)
        })
    })

    describe('selectors', () => {
        beforeEach(async () => {
            jest.spyOn(api, 'get').mockImplementation((url) => {
                if (url.includes('breakpoint_hits')) {
                    return Promise.resolve({
                        results: mockInstances,
                        count: mockInstances.length,
                        has_more: false,
                    })
                }
                return Promise.resolve({ results: mockBreakpoints, count: mockBreakpoints.length, has_more: false })
            })

            logic = liveDebuggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess', 'loadBreakpointInstancesSuccess'])
        })

        describe('selectedInstance', () => {
            it('returns instance matching selectedInstanceId', () => {
                logic.actions.selectInstance('inst-1')

                expect(logic.values.selectedInstance).toEqual(mockInstances[0])
            })

            it('returns null when no instance is selected', () => {
                expect(logic.values.selectedInstance).toBe(null)
            })

            it('returns null when selectedInstanceId does not exist', () => {
                logic.actions.selectInstance('non-existent')

                expect(logic.values.selectedInstance).toBe(null)
            })
        })

        describe('breakpointLines', () => {
            it('returns sorted line numbers for selected file', async () => {
                // Mock API to return only breakpoints for the current repo when file is selected
                jest.spyOn(api, 'get').mockResolvedValue({
                    results: mockBreakpoints.filter(
                        (bp) => bp.repository === 'PostHog/posthog' && bp.filename === 'capture_event.py'
                    ),
                    count: 2,
                    has_more: false,
                })

                logic = liveDebuggerLogic()
                logic.mount()

                logic.actions.setSelectedFilePath('capture_event.py')

                await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

                expect(logic.values.breakpointLines).toEqual([100, 200])
            })

            it('returns empty array when no file is selected', async () => {
                logic = liveDebuggerLogic()
                logic.mount()

                // Without a selected file, no breakpoints are loaded
                expect(logic.values.breakpointLines).toEqual([])
            })
        })

        describe('breakpointsByLine', () => {
            it('returns breakpoints indexed by line number for selected file', async () => {
                jest.spyOn(api, 'get').mockResolvedValue({
                    results: mockBreakpoints.filter(
                        (bp) => bp.repository === 'PostHog/posthog' && bp.filename === 'capture_event.py'
                    ),
                    count: 2,
                    has_more: false,
                })

                logic = liveDebuggerLogic()
                logic.mount()

                logic.actions.setSelectedFilePath('capture_event.py')

                await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

                const byLine = logic.values.breakpointsByLine

                expect(byLine[100]).toBeTruthy()
                expect(byLine[200]).toBeTruthy()
                expect(byLine[100].id).toBe('bp-1')
                expect(byLine[200].id).toBe('bp-2')
            })

            it('returns empty object when no file is selected', async () => {
                logic = liveDebuggerLogic()
                logic.mount()

                // Without a selected file, no breakpoints are loaded
                expect(logic.values.breakpointsByLine).toEqual({})
            })
        })

        describe('instancesByLine', () => {
            it('groups instances by line number for selected file', () => {
                logic.actions.setSelectedFilePath('capture_event.py')

                const byLine = logic.values.instancesByLine

                expect(byLine[100]).toHaveLength(1)
                expect(byLine[200]).toHaveLength(1)
                expect(byLine[100][0].id).toBe('inst-1')
                expect(byLine[200][0].id).toBe('inst-2')
            })

            it('returns all instances grouped by line when no file is selected', () => {
                const byLine = logic.values.instancesByLine

                expect(byLine[100]).toHaveLength(1)
                expect(byLine[200]).toHaveLength(1)
            })
        })

        describe('newInstanceIds', () => {
            it('returns instance IDs not in seenInstanceIds', () => {
                const newIds = logic.values.newInstanceIds

                expect(newIds.has('inst-1')).toBe(true)
                expect(newIds.has('inst-2')).toBe(true)
            })

            it('excludes instance IDs already in seenInstanceIds', () => {
                logic.actions.markInstanceAsOld('inst-1')

                const newIds = logic.values.newInstanceIds

                expect(newIds.has('inst-1')).toBe(false)
                expect(newIds.has('inst-2')).toBe(true)
            })
        })

        describe('hitCountsByLine', () => {
            it('counts hits per line for selected file', () => {
                logic.actions.setSelectedFilePath('capture_event.py')

                const counts = logic.values.hitCountsByLine

                expect(counts[100]).toBe(1)
                expect(counts[200]).toBe(1)
            })

            it('counts all hits when no file is selected', () => {
                const counts = logic.values.hitCountsByLine

                expect(counts[100]).toBe(1)
                expect(counts[200]).toBe(1)
            })
        })

        describe('newHitsByLine', () => {
            it('returns line numbers with new unseen hits', () => {
                const newHits = logic.values.newHitsByLine

                expect(newHits.has(100)).toBe(true)
                expect(newHits.has(200)).toBe(true)
            })

            it('excludes lines with only seen hits', () => {
                logic.actions.markInstanceAsOld('inst-1')
                logic.actions.markInstanceAsOld('inst-2')

                const newHits = logic.values.newHitsByLine

                expect(newHits.size).toBe(0)
            })

            it('filters by selected file', () => {
                logic.actions.setSelectedFilePath('other_file.py')

                const newHits = logic.values.newHitsByLine

                expect(newHits.size).toBe(0)
            })
        })

        describe('hitsForSelectedLine', () => {
            it('returns instances for selected line', () => {
                logic.actions.showHitsForLine(100)

                const hits = logic.values.hitsForSelectedLine

                expect(hits).toHaveLength(1)
                expect(hits[0].id).toBe('inst-1')
            })

            it('returns empty array when no line is selected', () => {
                expect(logic.values.hitsForSelectedLine).toEqual([])
            })

            it('returns empty array when selected line has no hits', () => {
                logic.actions.showHitsForLine(999)

                expect(logic.values.hitsForSelectedLine).toEqual([])
            })
        })
    })

    describe('multi-repository edge cases', () => {
        it('distinguishes breakpoints by repository when toggling', async () => {
            // Mock breakpoints for PostHog/posthog repo only
            jest.spyOn(api, 'get').mockResolvedValue({
                results: mockBreakpoints.filter((bp) => bp.repository === 'PostHog/posthog'),
                count: 2,
                has_more: false,
            })
            jest.spyOn(api, 'delete').mockResolvedValue({})

            logic = liveDebuggerLogic()
            logic.mount()

            // Set file to load breakpoints
            logic.actions.setSelectedFilePath('capture_event.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            // Delete PostHog/posthog breakpoint
            await expectLogic(logic, () => {
                logic.actions.toggleBreakpoint('capture_event.py', 100, 'PostHog/posthog')
            }).toDispatchActions(['toggleBreakpoint'])

            expect(api.delete).toHaveBeenCalledWith('api/projects/@current/live_debugger_breakpoints/bp-1/')
        })
    })

    describe('file switching', () => {
        it('clears breakpoint display when switching files', async () => {
            const mockGet = jest.spyOn(api, 'get')

            // Backend correctly returns different breakpoints for different files
            mockGet.mockImplementation((url: string) => {
                if (url.includes('breakpoint_hits')) {
                    return Promise.resolve({ results: [], count: 0, has_more: false })
                }
                if (url.includes('filename=capture_event.py')) {
                    // File A has 2 breakpoints
                    return Promise.resolve({
                        results: mockBreakpoints.filter(
                            (bp) => bp.filename === 'capture_event.py' && bp.repository === 'PostHog/posthog'
                        ),
                        count: 2,
                        has_more: false,
                    })
                }
                if (url.includes('filename=other_file.py')) {
                    // File B has NO breakpoints
                    return Promise.resolve({ results: [], count: 0, has_more: false })
                }
                return Promise.resolve({ results: [], count: 0, has_more: false })
            })

            logic = liveDebuggerLogic()
            logic.mount()

            // Load file A which has breakpoints
            logic.actions.setSelectedFilePath('capture_event.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            expect(logic.values.breakpointLines).toEqual([100, 200])
            expect(logic.values.breakpoints.length).toBe(2)

            // Switch to file B which has NO breakpoints
            logic.actions.setSelectedFilePath('other_file.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            // The breakpoints should be cleared
            expect(logic.values.breakpoints).toEqual([])
            expect(logic.values.breakpointLines).toEqual([])
        })

        it('replaces breakpoints when switching between files with different breakpoints', async () => {
            const fileABreakpoints: Breakpoint[] = [
                {
                    id: 'bp-a1',
                    repository: 'PostHog/posthog',
                    filename: 'fileA.py',
                    line_number: 10,
                    enabled: true,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                {
                    id: 'bp-a2',
                    repository: 'PostHog/posthog',
                    filename: 'fileA.py',
                    line_number: 20,
                    enabled: true,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
            ]

            const fileBBreakpoints: Breakpoint[] = [
                {
                    id: 'bp-b1',
                    repository: 'PostHog/posthog',
                    filename: 'fileB.py',
                    line_number: 30,
                    enabled: true,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
            ]

            const mockGet = jest.spyOn(api, 'get')
            mockGet.mockImplementation((url: string) => {
                if (url.includes('breakpoint_hits')) {
                    return Promise.resolve({ results: [], count: 0, has_more: false })
                }
                if (url.includes('filename=fileA.py')) {
                    return Promise.resolve({ results: fileABreakpoints, count: 2, has_more: false })
                }
                if (url.includes('filename=fileB.py')) {
                    return Promise.resolve({ results: fileBBreakpoints, count: 1, has_more: false })
                }
                return Promise.resolve({ results: [], count: 0, has_more: false })
            })

            logic = liveDebuggerLogic()
            logic.mount()

            // Select fileA
            logic.actions.setSelectedFilePath('fileA.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            expect(logic.values.breakpointLines).toEqual([10, 20])
            expect(logic.values.breakpoints.map((bp) => bp.id)).toEqual(['bp-a1', 'bp-a2'])

            // Switch to fileB
            logic.actions.setSelectedFilePath('fileB.py')
            await expectLogic(logic).toDispatchActions(['loadBreakpointsSuccess'])

            expect(logic.values.breakpointLines).toEqual([30])
            expect(logic.values.breakpoints.map((bp) => bp.id)).toEqual(['bp-b1'])
        })
    })
})
