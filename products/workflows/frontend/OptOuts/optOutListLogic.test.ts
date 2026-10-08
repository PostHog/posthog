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
        jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:opt-outs')

        await expectLogic(logic, () => {
            logic.actions.exportCsv()
        }).toDispatchActions(['exportCsvSuccess'])

        expect(capture).toHaveBeenCalledWith('messaging opt-outs exported')
    })

    it.each([
        {
            optedOut: 2,
            outcome: 'captures the import count',
            expected: [['messaging opt-outs imported', { count: 2 }]],
        },
        { optedOut: 0, outcome: 'captures nothing', expected: [] },
    ])('$outcome when the import opts out $optedOut recipients', async ({ optedOut, expected }) => {
        jest.spyOn(messagingApi, 'messagingPreferencesBulkAddOptOutsCreate').mockResolvedValue({
            total: 3,
            opted_out: optedOut,
            skipped: 3 - optedOut,
            errors: [],
        })
        // jsdom cannot stream a File through Papa, so hand the parsed rows straight to its callback.
        jest.spyOn(Papa, 'parse').mockImplementation(((
            _file: File,
            config: { complete: (results: { data: string[][] }) => void }
        ) =>
            config.complete({
                data: [['email'], ['jamie@example.com'], ['alex@example.com'], ['sam@example.com']],
            })) as unknown as typeof Papa.parse)
        logic.actions.setCsvFile(new File([''], 'opt-outs.csv'))

        await expectLogic(logic, () => {
            logic.actions.importCsv()
        }).toDispatchActions(['importCsvSuccess'])

        expect(capture.mock.calls.filter(([event]) => event === 'messaging opt-outs imported')).toEqual(expected)
    })
})
