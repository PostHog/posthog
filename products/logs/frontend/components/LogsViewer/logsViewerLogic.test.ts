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
        const logsLength = mockLogs.length

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
                    logic.actions.moveCursorDown(logsLength)
                })
                    .toDispatchActions(['moveCursorDown', 'setCursorIndex'])
                    .toMatchValues({
                        cursorIndex: 0,
                    })
            })

            it('highlights next log in sequence', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown(logsLength)
                })
                    .toDispatchActions(['moveCursorDown', 'setCursorIndex'])
                    .toMatchValues({
                        cursorIndex: 1,
                    })
            })

            it('does nothing when at last log', async () => {
                logic.actions.setCursorIndex(2)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorDown(logsLength)
                })
                    .toDispatchActions(['moveCursorDown'])
                    .toNotHaveDispatchedActions(['setCursorIndex'])
            })
        })

        describe('moveCursorUp', () => {
            it('highlights last log when none is highlighted', async () => {
                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp(logsLength)
                })
                    .toDispatchActions(['moveCursorUp', 'setCursorIndex'])
                    .toMatchValues({
                        cursorIndex: 2,
                    })
            })

            it('highlights previous log in sequence', async () => {
                logic.actions.setCursorIndex(1)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp(logsLength)
                })
                    .toDispatchActions(['moveCursorUp', 'setCursorIndex'])
                    .toMatchValues({
                        cursorIndex: 0,
                    })
            })

            it('does nothing when at first log', async () => {
                logic.actions.setCursorIndex(0)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.moveCursorUp(logsLength)
                })
                    .toDispatchActions(['moveCursorUp'])
                    .toNotHaveDispatchedActions(['setCursorIndex'])
            })
        })
    })

    describe('empty logs', () => {
        beforeEach(() => {
            logic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            logic.mount()
        })

        it('moveCursorDown does nothing when logs are empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveCursorDown(0)
            })
                .toDispatchActions(['moveCursorDown'])
                .toNotHaveDispatchedActions(['setCursorIndex'])
        })

        it('moveCursorUp does nothing when logs are empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveCursorUp(0)
            })
                .toDispatchActions(['moveCursorUp'])
                .toNotHaveDispatchedActions(['setCursorIndex'])
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
})
