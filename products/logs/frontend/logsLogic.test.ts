import { expectLogic } from 'kea-test-utils'

import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { SparklineTimezone, logsLogic } from './logsLogic'

const createMockLog = (uuid: string): LogMessage => ({
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
})

describe('logsLogic', () => {
    let logic: ReturnType<typeof logsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = logsLogic({ tabId: 'test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('keyboard navigation', () => {
        const mockLogs = [createMockLog('log-1'), createMockLog('log-2'), createMockLog('log-3')]

        describe('highlightNextLog', () => {
            it('highlights first log when none is highlighted', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-1',
                    })
            })

            it('highlights next log in sequence', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-2',
                    })
            })

            it('loads more logs when at last log and more available', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-3')
                logic.actions.setHasMoreLogsToLoad(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                }).toDispatchActions(['highlightNextLog', 'fetchNextLogsPage'])
            })

            it('does nothing when at last log and no more to load', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-3')
                logic.actions.setHasMoreLogsToLoad(false)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId', 'fetchNextLogsPage'])
            })

            it('does nothing when logs are empty', async () => {
                logic.actions.fetchLogsSuccess([])
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })
        })

        describe('highlightPreviousLog', () => {
            it('highlights last log when none is highlighted', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-3',
                    })
            })

            it('highlights previous log in sequence', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-2')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-1',
                    })
            })

            it('does nothing when at first log', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })

            it('does nothing when logs are empty', async () => {
                logic.actions.fetchLogsSuccess([])
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })
        })

        describe('toggleExpandLog', () => {
            it('expands a log when not expanded', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleExpandLog('log-1')
                }).toDispatchActions(['toggleExpandLog'])

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
            })

            it('collapses a log when already expanded', async () => {
                logic.actions.toggleExpandLog('log-1')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)

                await expectLogic(logic, () => {
                    logic.actions.toggleExpandLog('log-1')
                }).toDispatchActions(['toggleExpandLog'])

                expect(logic.values.expandedLogIds.has('log-1')).toBe(false)
            })

            it('supports multiple expanded logs', async () => {
                logic.actions.toggleExpandLog('log-1')
                logic.actions.toggleExpandLog('log-2')
                logic.actions.toggleExpandLog('log-3')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-2')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-3')).toBe(true)

                logic.actions.toggleExpandLog('log-2')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-2')).toBe(false)
                expect(logic.values.expandedLogIds.has('log-3')).toBe(true)
            })
        })
    })

    describe('sparklineTimezone', () => {
        it('updates when setSparklineTimezone is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSparklineTimezone(SparklineTimezone.Device)
            })
                .toDispatchActions(['setSparklineTimezone'])
                .toMatchValues({
                    sparklineTimezone: SparklineTimezone.Device,
                })

            await expectLogic(logic, () => {
                logic.actions.setSparklineTimezone(SparklineTimezone.UTC)
            })
                .toDispatchActions(['setSparklineTimezone'])
                .toMatchValues({
                    sparklineTimezone: SparklineTimezone.UTC,
                })
        })
    })
})
