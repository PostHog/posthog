import { expectLogic } from 'kea-test-utils'
import Papa from 'papaparse'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'

import { optOutListLogic } from './optOutListLogic'

describe('optOutListLogic usage tracking', () => {
    let logic: ReturnType<typeof optOutListLogic.build>
    let capture: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(messagingApi, 'messagingPreferencesOptOutsRetrieve').mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
        capture = jest.spyOn(posthog, 'capture')
        logic = optOutListLogic({})
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('captures the export once the file downloads', async () => {
        jest.spyOn(api.messaging, 'exportOptOutsCsv').mockResolvedValue(new Blob(['identifier\n']))
        URL.createObjectURL = jest.fn(() => 'blob:opt-outs')

        await expectLogic(logic, () => {
            logic.actions.exportCsv()
        }).toDispatchActions(['exportCsvSuccess'])

        expect(capture).toHaveBeenCalledWith('messaging opt-outs exported')
    })

    it('captures the import with the number of recipients it opted out', async () => {
        jest.spyOn(messagingApi, 'messagingPreferencesBulkAddOptOutsCreate').mockResolvedValue({
            total: 3,
            opted_out: 2,
            skipped: 1,
            errors: [],
        })
        // jsdom cannot stream a File through Papa, so hand the parsed rows straight to its callback.
        jest.spyOn(Papa, 'parse').mockImplementation(((_file: File, config: Papa.ParseLocalConfig<string[]>) => {
            config.complete?.(
                {
                    data: [['email'], ['jamie@example.com'], ['alex@example.com'], ['sam@example.com']],
                } as Papa.ParseResult<string[]>,
                _file
            )
        }) as any)
        logic.actions.setCsvFile(new File([''], 'opt-outs.csv'))

        await expectLogic(logic, () => {
            logic.actions.importCsv()
        }).toDispatchActions(['importCsvSuccess'])

        expect(capture).toHaveBeenCalledWith('messaging opt-outs imported', { count: 2 })
    })
})
