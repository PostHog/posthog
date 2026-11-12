import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { releasesImportAllCreate } from './generated/api'
import { releaseImportLogic } from './releaseImportLogic'

jest.mock('./generated/api', () => ({
    releasesList: jest.fn(async () => ({ results: [], count: 0, next: null })),
    releasesImportAllCreate: jest.fn(),
}))

describe('releaseImportLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it.each([
        ['marks the project once the import succeeds', true, 'idle', true],
        ['offers a retry when the import fails', false, 'failed', false],
    ])('%s', async (_name, succeeds, state, marked) => {
        if (succeeds) {
            jest.mocked(releasesImportAllCreate).mockResolvedValue({ created_count: 3 })
        } else {
            jest.mocked(releasesImportAllCreate).mockRejectedValue(new Error('offline'))
        }
        const logic = releaseImportLogic()
        logic.mount()

        logic.actions.runAutoImport()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.autoImportState).toBe(state)
        expect(Object.keys(logic.values.autoImportedProjects).length > 0).toBe(marked)
    })
})
