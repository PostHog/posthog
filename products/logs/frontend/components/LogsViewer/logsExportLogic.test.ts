import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { getExportColumns, logsExportLogic } from './logsExportLogic'
import { logsViewerLogic } from './logsViewerLogic'

jest.mock('lib/api')
jest.mock('lib/utils/copyToClipboard')

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
            ;(api.get as jest.Mock).mockResolvedValue({
                logs_distinct_id_attribute_key: 'posthogDistinctId',
                logs_distinct_id_attribute_keys: ['posthogDistinctId'],
                logs_session_id_attribute_keys: ['posthogSessionId'],
            })
            ;(api.logs.query as jest.Mock).mockResolvedValue({
                results: [],
                hasMore: false,
                nextCursor: null,
                maxExportableLogs: 10_000,
            })
            ;(api.logs.sparkline as jest.Mock).mockResolvedValue([])

            viewerLogic = logsViewerLogic({ id: 'test-tab' })
            viewerLogic.mount()

            exportLogic = logsExportLogic({ id: 'test-tab' })
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

        describe('exportSelectedAsCsv', () => {
            it('prefixes cells starting with a formula character so spreadsheets read them as text', async () => {
                const createObjectURL = jest.fn((_blob: Blob) => 'blob:logs-export')
                const originalCreateObjectURL = URL.createObjectURL
                const originalRevokeObjectURL = URL.revokeObjectURL
                URL.createObjectURL = createObjectURL
                URL.revokeObjectURL = jest.fn()
                const anchorClick = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
                try {
                    const log: LogMessage = {
                        uuid: 'log-1',
                        trace_id: 'trace-1',
                        span_id: 'span-1',
                        body: '=1+1',
                        attributes: {},
                        timestamp: '2024-01-01T00:00:00Z',
                        observed_timestamp: '2024-01-01T00:00:00Z',
                        severity_text: 'info',
                        severity_number: 9,
                        level: 'info',
                        resource_attributes: {},
                        instrumentation_scope: 'test',
                        event_name: 'log',
                    }
                    viewerLogic.actions.setLogs([log])
                    viewerLogic.actions.setSelectedLogIds({ 'log-1': true })

                    await expectLogic(exportLogic, () => {
                        exportLogic.actions.exportSelectedAsCsv()
                    }).toFinishAllListeners()

                    expect(anchorClick).toHaveBeenCalledTimes(1)
                    const csv = await createObjectURL.mock.calls[0][0].text()
                    expect(csv.split('\r\n')).toEqual([
                        'timestamp,severity_text,body,attributes,resource_attributes',
                        `2024-01-01T00:00:00Z,info,"'=1+1",{},{}`,
                    ])
                } finally {
                    URL.createObjectURL = originalCreateObjectURL
                    URL.revokeObjectURL = originalRevokeObjectURL
                    anchorClick.mockRestore()
                }
            })
        })
    })
})
