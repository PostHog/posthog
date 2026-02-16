import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

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
    })
})
