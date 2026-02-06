import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { getExportColumns, logsExportLogic } from './logsExportLogic'
import { logsViewerLogic } from './logsViewerLogic'

jest.mock('lib/api')
jest.mock('lib/utils/copyToClipboard')

const createMockParsedLog = (uuid: string, body: string = `Log ${uuid}`): ParsedLogMessage => {
    const baseLog = {
        uuid,
        trace_id: 'trace-1',
        span_id: 'span-1',
        body,
        attributes: { 'service.name': 'test-service', custom: 'value' },
        timestamp: '2024-01-01T00:00:00Z',
        observed_timestamp: '2024-01-01T00:00:00Z',
        severity_text: 'info' as const,
        severity_number: 9,
        level: 'info' as const,
        resource_attributes: { 'host.name': 'localhost' },
        instrumentation_scope: 'test',
        event_name: 'log',
    }
    return {
        ...baseLog,
        cleanBody: body,
        parsedBody: null,
        originalLog: baseLog,
    }
}

const mockLogs = [
    createMockParsedLog('log-1', 'First log message'),
    createMockParsedLog('log-2', 'Second log message'),
    createMockParsedLog('log-3', 'Third log message'),
]

describe('logsExportLogic', () => {
    describe('getExportColumns', () => {
        it('includes raw attribute columns when no attribute columns configured', () => {
            const columns = getExportColumns([])
            expect(columns).toEqual(['timestamp', 'severity_text', 'body', 'attributes', 'resource_attributes'])
        })

        it('excludes raw attribute columns when attribute columns are configured', () => {
            const columns = getExportColumns(['service.name', 'http.method'])
            expect(columns).toEqual(['timestamp', 'severity_text', 'service.name', 'http.method', 'body'])
        })

        it('places attribute columns between severity_text and body', () => {
            const columns = getExportColumns(['custom.attr'])
            expect(columns.indexOf('severity_text')).toBeLessThan(columns.indexOf('custom.attr'))
            expect(columns.indexOf('custom.attr')).toBeLessThan(columns.indexOf('body'))
        })

        it('preserves order of attribute columns', () => {
            const columns = getExportColumns(['z.attr', 'a.attr', 'm.attr'])
            expect(columns).toEqual(['timestamp', 'severity_text', 'z.attr', 'a.attr', 'm.attr', 'body'])
        })
    })

    describe('logic', () => {
        let viewerLogic: ReturnType<typeof logsViewerLogic.build>
        let exportLogic: ReturnType<typeof logsExportLogic.build>

        beforeEach(() => {
            localStorage.clear()
            initKeaTests()
            jest.clearAllMocks()

            viewerLogic = logsViewerLogic({ tabId: 'test-tab', logs: mockLogs, orderBy: 'latest' })
            viewerLogic.mount()

            exportLogic = logsExportLogic({ tabId: 'test-tab', orderBy: 'latest' })
            exportLogic.mount()
        })

        afterEach(() => {
            exportLogic?.unmount()
            viewerLogic?.unmount()
        })

        describe('copySelectedLogs', () => {
            it('dispatches copySelectedLogs action', async () => {
                await expectLogic(exportLogic, () => {
                    exportLogic.actions.copySelectedLogs()
                }).toDispatchActions(['copySelectedLogs'])
            })

            it('calls copyToClipboard', async () => {
                await expectLogic(exportLogic, () => {
                    exportLogic.actions.copySelectedLogs()
                }).toFinishAllListeners()

                expect(copyToClipboard).toHaveBeenCalled()
            })
        })

        describe('exportServerSide', () => {
            beforeEach(() => {
                ;(api.logs.exportQuery as jest.Mock).mockResolvedValue({})
            })

            it('calls API with correct query parameters', async () => {
                await expectLogic(exportLogic, () => {
                    exportLogic.actions.exportServerSide(100)
                }).toFinishAllListeners()

                expect(api.logs.exportQuery).toHaveBeenCalledWith(
                    expect.objectContaining({
                        columns: expect.arrayContaining(['timestamp', 'severity_text', 'body']),
                    })
                )
            })

            it('includes attribute columns when configured', async () => {
                viewerLogic.actions.toggleAttributeColumn('service.name')
                await expectLogic(viewerLogic).toFinishAllListeners()

                await expectLogic(exportLogic, () => {
                    exportLogic.actions.exportServerSide(50)
                }).toFinishAllListeners()

                expect(api.logs.exportQuery).toHaveBeenCalledWith(
                    expect.objectContaining({
                        columns: ['timestamp', 'severity_text', 'service.name', 'body'],
                    })
                )
            })

            it('includes raw attributes when no columns configured', async () => {
                await expectLogic(exportLogic, () => {
                    exportLogic.actions.exportServerSide(50)
                }).toFinishAllListeners()

                expect(api.logs.exportQuery).toHaveBeenCalledWith(
                    expect.objectContaining({
                        columns: ['timestamp', 'severity_text', 'body', 'attributes', 'resource_attributes'],
                    })
                )
            })
        })
    })
})
