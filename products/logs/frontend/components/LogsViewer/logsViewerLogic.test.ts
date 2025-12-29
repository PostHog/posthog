import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { logsViewerLogic } from './logsViewerLogic'

const createMockParsedLog = (uuid: string): ParsedLogMessage => ({
    uuid,
    trace_id: 'trace-1',
    span_id: 'span-1',
    body: `Log ${uuid}`,
    attributes: {},
    timestamp: '2024-01-01T00:00:00Z',
    observed_timestamp: '2024-01-01T00:00:00Z',
    severity_text: 'info',
    severity_number: 9,
    level: 'info',
    resource_attributes: {},
    instrumentation_scope: 'test',
    event_name: 'log',
    cleanBody: `Log ${uuid}`,
    parsedBody: null,
})

const mockLogs = [createMockParsedLog('log-1'), createMockParsedLog('log-2'), createMockParsedLog('log-3')]

describe('logsViewerLogic', () => {
    let logic: ReturnType<typeof logsViewerLogic.build>

    beforeEach(() => {
        // Clear localStorage to reset persisted state
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('cursor navigation', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('sets cursor index', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCursorIndex(0)
            }).toMatchValues({
                cursorIndex: 0,
            })
        })

        it('clears cursor when set to null', async () => {
            logic.actions.setCursorIndex(0)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setCursorIndex(null)
            }).toMatchValues({
                cursorIndex: null,
            })
        })

        describe('moveCursorDown', () => {
            it('highlights first log when none is highlighted', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown()
                })
                    .toDispatchActions(['moveCursorDown', 'setCursor'])
                    .toMatchValues({
                        cursorIndex: 0,
                    })
            })

            it('highlights next log in sequence', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown()
                })
                    .toDispatchActions(['moveCursorDown', 'setCursor'])
                    .toMatchValues({
                        cursorIndex: 1,
                    })
            })

            it('does nothing when at last log', async () => {
                logic.actions.setCursorIndex(2)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown()
                })
                    .toDispatchActions(['moveCursorDown'])
                    .toNotHaveDispatchedActions(['setCursor'])
            })
        })

        describe('moveCursorUp', () => {
            it('highlights last log when none is highlighted', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp()
                })
                    .toDispatchActions(['moveCursorUp', 'setCursor'])
                    .toMatchValues({
                        cursorIndex: 2,
                    })
            })

            it('highlights previous log in sequence', async () => {
                logic.actions.setCursorIndex(1)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp()
                })
                    .toDispatchActions(['moveCursorUp', 'setCursor'])
                    .toMatchValues({
                        cursorIndex: 0,
                    })
            })

            it('does nothing when at first log', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp()
                })
                    .toDispatchActions(['moveCursorUp'])
                    .toNotHaveDispatchedActions(['setCursor'])
            })
        })

        describe('shiftSelect', () => {
            it('moveCursorDown with shiftSelect selects the new row', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown(true)
                })
                    .toDispatchActions(['moveCursorDown', 'setCursor', 'setSelectedLogIds'])
                    .toMatchValues({
                        cursorIndex: 1,
                        selectedLogIds: { 'log-2': true },
                    })
            })

            it('moveCursorUp with shiftSelect selects the new row', async () => {
                logic.actions.setCursorIndex(2)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp(true)
                })
                    .toDispatchActions(['moveCursorUp', 'setCursor', 'setSelectedLogIds'])
                    .toMatchValues({
                        cursorIndex: 1,
                        selectedLogIds: { 'log-2': true },
                    })
            })

            it('moveCursorDown with shiftSelect from no cursor selects first row', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown(true)
                })
                    .toDispatchActions(['moveCursorDown', 'setCursor', 'setSelectedLogIds'])
                    .toMatchValues({
                        cursorIndex: 0,
                        selectedLogIds: { 'log-1': true },
                    })
            })

            it('moveCursorUp with shiftSelect from no cursor selects last row', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp(true)
                })
                    .toDispatchActions(['moveCursorUp', 'setCursor', 'setSelectedLogIds'])
                    .toMatchValues({
                        cursorIndex: 2,
                        selectedLogIds: { 'log-3': true },
                    })
            })

            it('shiftSelect accumulates selections when moving down', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                logic.actions.moveCursorDown(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown(true)
                }).toMatchValues({
                    cursorIndex: 2,
                    selectedLogIds: { 'log-2': true, 'log-3': true },
                })
            })
        })
    })

    describe('empty logs', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: [], orderBy: 'latest' })
            logic.mount()
        })

        it('moveCursorDown does nothing when logs are empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveCursorDown()
            })
                .toDispatchActions(['moveCursorDown'])
                .toNotHaveDispatchedActions(['setCursor'])
        })

        it('moveCursorUp does nothing when logs are empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveCursorUp()
            })
                .toDispatchActions(['moveCursorUp'])
                .toNotHaveDispatchedActions(['setCursor'])
        })
    })

    describe('expansion', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })
        it('expands a log when not expanded', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleExpandLog('log-1')
            }).toMatchValues({
                expandedLogIds: { 'log-1': true },
            })
        })

        it('collapses a log when already expanded', async () => {
            logic.actions.toggleExpandLog('log-1')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.expandedLogIds['log-1']).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.toggleExpandLog('log-1')
            }).toMatchValues({
                expandedLogIds: {},
            })
        })

        it('supports multiple expanded logs', async () => {
            logic.actions.toggleExpandLog('log-1')
            logic.actions.toggleExpandLog('log-2')
            logic.actions.toggleExpandLog('log-3')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.expandedLogIds).toEqual({
                'log-1': true,
                'log-2': true,
                'log-3': true,
            })

            logic.actions.toggleExpandLog('log-2')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.expandedLogIds).toEqual({
                'log-1': true,
                'log-3': true,
            })
        })
    })

    describe('pinning', () => {
        const mockLog1 = createMockParsedLog('log-1')
        const mockLog2 = createMockParsedLog('log-2')

        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('pins a log when not pinned', async () => {
            await expectLogic(logic, () => {
                logic.actions.togglePinLog(mockLog1)
            }).toMatchValues({
                pinnedLogs: { 'log-1': mockLog1 },
            })
        })

        it('unpins a log when already pinned', async () => {
            await expectLogic(logic, () => {
                logic.actions.togglePinLog(mockLog1)
            }).toMatchValues({
                pinnedLogs: { 'log-1': mockLog1 },
            })

            await expectLogic(logic, () => {
                logic.actions.togglePinLog(mockLog1)
            }).toMatchValues({
                pinnedLogs: {},
            })
        })

        it('supports multiple pinned logs', async () => {
            logic.actions.togglePinLog(mockLog1)
            logic.actions.togglePinLog(mockLog2)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.pinnedLogs).toEqual({
                'log-1': mockLog1,
                'log-2': mockLog2,
            })
        })

        it('pinnedLogsArray returns array of pinned logs', async () => {
            await expectLogic(logic, () => {
                logic.actions.togglePinLog(mockLog1)
                logic.actions.togglePinLog(mockLog2)
            }).toFinishAllListeners()

            const pinnedArray = logic.values.pinnedLogsArray
            expect(pinnedArray).toHaveLength(2)
            expect(pinnedArray).toContainEqual(mockLog1)
            expect(pinnedArray).toContainEqual(mockLog2)
        })

        it('provides O(1) lookup via pinnedLogs record', async () => {
            logic.actions.togglePinLog(mockLog1)
            await expectLogic(logic).toFinishAllListeners()

            expect(!!logic.values.pinnedLogs['log-1']).toBe(true)
            expect(!!logic.values.pinnedLogs['log-2']).toBe(false)
        })
    })

    describe('focus state', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('defaults to not focused', () => {
            expect(logic.values.isFocused).toBe(false)
        })

        it('sets focus state', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFocused(true)
            }).toMatchValues({
                isFocused: true,
            })

            await expectLogic(logic, () => {
                logic.actions.setFocused(false)
            }).toMatchValues({
                isFocused: false,
            })
        })
    })

    describe('display options', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('defaults wrapBody to true', () => {
            expect(logic.values.wrapBody).toBe(true)
        })

        it('sets wrapBody', async () => {
            await expectLogic(logic, () => {
                logic.actions.setWrapBody(false)
            }).toMatchValues({
                wrapBody: false,
            })
        })

        it('defaults prettifyJson to true', () => {
            expect(logic.values.prettifyJson).toBe(true)
        })

        it('sets prettifyJson', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPrettifyJson(false)
            }).toMatchValues({
                prettifyJson: false,
            })
        })
    })

    describe('timezone', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('defaults to UTC', () => {
            expect(logic.values.timezone).toBe('UTC')
        })

        it('sets timezone to IANA string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTimezone('America/New_York')
            }).toMatchValues({
                timezone: 'America/New_York',
            })
        })

        it('sets timezone back to UTC', async () => {
            logic.actions.setTimezone('Europe/London')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setTimezone('UTC')
            }).toMatchValues({
                timezone: 'UTC',
            })
        })
    })

    describe('multi-select', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('defaults to no selection', () => {
            expect(logic.values.selectedLogIds).toEqual({})
            expect(logic.values.isSelectionActive).toBe(false)
            expect(logic.values.selectedCount).toBe(0)
            expect(logic.values.selectedLogsArray).toEqual([])
        })

        describe('toggleSelectLog', () => {
            it('selects a log when not selected', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleSelectLog('log-1')
                }).toMatchValues({
                    selectedLogIds: { 'log-1': true },
                    isSelectionActive: true,
                    selectedCount: 1,
                })
            })

            it('deselects a log when already selected', async () => {
                logic.actions.toggleSelectLog('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.toggleSelectLog('log-1')
                }).toMatchValues({
                    selectedLogIds: {},
                    isSelectionActive: false,
                    selectedCount: 0,
                })
            })

            it('supports multiple selections', async () => {
                logic.actions.toggleSelectLog('log-1')
                logic.actions.toggleSelectLog('log-3')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-3': true,
                })
                expect(logic.values.selectedCount).toBe(2)
            })
        })

        describe('clearSelection', () => {
            it('clears all selections', async () => {
                logic.actions.toggleSelectLog('log-1')
                logic.actions.toggleSelectLog('log-2')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.selectedCount).toBe(2)

                await expectLogic(logic, () => {
                    logic.actions.clearSelection()
                }).toMatchValues({
                    selectedLogIds: {},
                    isSelectionActive: false,
                    selectedCount: 0,
                })
            })
        })

        describe('selectAll', () => {
            it('selects all logs when no argument provided', async () => {
                await expectLogic(logic, () => {
                    logic.actions.selectAll()
                }).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-2': true,
                    'log-3': true,
                })
                expect(logic.values.selectedCount).toBe(3)
            })

            it('selects only provided logs when argument given', async () => {
                const subset = [mockLogs[0], mockLogs[2]]
                await expectLogic(logic, () => {
                    logic.actions.selectAll(subset)
                }).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-3': true,
                })
                expect(logic.values.selectedCount).toBe(2)
            })
        })

        describe('selectLogRange', () => {
            it('selects range from lower to higher index', async () => {
                await expectLogic(logic, () => {
                    logic.actions.selectLogRange(0, 2)
                }).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-2': true,
                    'log-3': true,
                })
            })

            it('selects range from higher to lower index', async () => {
                await expectLogic(logic, () => {
                    logic.actions.selectLogRange(2, 0)
                }).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-2': true,
                    'log-3': true,
                })
            })

            it('preserves existing selections when adding range', async () => {
                logic.actions.toggleSelectLog('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.selectLogRange(1, 2)
                }).toFinishAllListeners()

                expect(logic.values.selectedLogIds).toEqual({
                    'log-1': true,
                    'log-2': true,
                    'log-3': true,
                })
            })
        })

        describe('selectedLogsArray', () => {
            it('returns array of selected log objects in order', async () => {
                logic.actions.toggleSelectLog('log-3')
                logic.actions.toggleSelectLog('log-1')
                await expectLogic(logic).toFinishAllListeners()

                const selected = logic.values.selectedLogsArray
                expect(selected).toHaveLength(2)
                // Should maintain logs array order, not selection order
                expect(selected[0].uuid).toBe('log-1')
                expect(selected[1].uuid).toBe('log-3')
            })
        })

        describe('selection cleared on logs change', () => {
            it('clears selection when setLogs is called', async () => {
                logic.actions.toggleSelectLog('log-1')
                logic.actions.toggleSelectLog('log-2')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.selectedCount).toBe(2)

                await expectLogic(logic, () => {
                    logic.actions.setLogs([createMockParsedLog('new-log')])
                }).toMatchValues({
                    selectedLogIds: {},
                    isSelectionActive: false,
                })
            })
        })
    })

    describe('attribute columns', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        describe('moveAttributeColumn', () => {
            beforeEach(async () => {
                // Set up initial columns: [A, B, C]
                logic.actions.toggleAttributeColumn('A')
                logic.actions.toggleAttributeColumn('B')
                logic.actions.toggleAttributeColumn('C')
                await expectLogic(logic).toFinishAllListeners()
            })

            it('moves column left', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveAttributeColumn('B', 'left')
                }).toMatchValues({
                    attributeColumns: ['B', 'A', 'C'],
                })
            })

            it('moves column right', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveAttributeColumn('B', 'right')
                }).toMatchValues({
                    attributeColumns: ['A', 'C', 'B'],
                })
            })

            it('does nothing when moving first column left', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveAttributeColumn('A', 'left')
                }).toMatchValues({
                    attributeColumns: ['A', 'B', 'C'],
                })
            })

            it('does nothing when moving last column right', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveAttributeColumn('C', 'right')
                }).toMatchValues({
                    attributeColumns: ['A', 'B', 'C'],
                })
            })

            it('does nothing for non-existent column', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveAttributeColumn('Z', 'left')
                }).toMatchValues({
                    attributeColumns: ['A', 'B', 'C'],
                })
            })
        })
    })

    describe('per-row prettification', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('defaults to empty set', () => {
            expect(logic.values.prettifiedLogIds).toEqual(new Set())
            expect(logic.values.prettifiedLogIds.has('log-1')).toBe(false)
        })

        it('prettifies a log when not prettified', async () => {
            await expectLogic(logic, () => {
                logic.actions.togglePrettifyLog('log-1')
            }).toFinishAllListeners()

            expect(logic.values.prettifiedLogIds.has('log-1')).toBe(true)
        })

        it('un-prettifies a log when already prettified', async () => {
            logic.actions.togglePrettifyLog('log-1')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.togglePrettifyLog('log-1')
            }).toFinishAllListeners()

            expect(logic.values.prettifiedLogIds.has('log-1')).toBe(false)
        })

        it('supports multiple prettified logs', async () => {
            logic.actions.togglePrettifyLog('log-1')
            logic.actions.togglePrettifyLog('log-3')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.prettifiedLogIds.has('log-1')).toBe(true)
            expect(logic.values.prettifiedLogIds.has('log-2')).toBe(false)
            expect(logic.values.prettifiedLogIds.has('log-3')).toBe(true)
        })

        it('triggers recomputeRowHeights when toggling', async () => {
            await expectLogic(logic, () => {
                logic.actions.togglePrettifyLog('log-1')
            }).toDispatchActions(['togglePrettifyLog', 'recomputeRowHeights'])
        })

        it('clears when setLogs is called', async () => {
            logic.actions.togglePrettifyLog('log-1')
            logic.actions.togglePrettifyLog('log-2')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.prettifiedLogIds.size).toBe(2)

            await expectLogic(logic, () => {
                logic.actions.setLogs([createMockParsedLog('new-log')])
            }).toFinishAllListeners()

            expect(logic.values.prettifiedLogIds.size).toBe(0)
        })
    })
})
