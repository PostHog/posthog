import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { AppContext } from '../../../../frontend/src/types'
import * as api from '../generated/api'
import { legalDocumentsLogic } from './legalDocumentsLogic'

jest.mock('../generated/api', () => ({
    legalDocumentsList: jest.fn().mockResolvedValue({ results: [] }),
}))

describe('legalDocumentsLogic', () => {
    let logic: ReturnType<typeof legalDocumentsLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('does not call the API with the "@current" sentinel while the organization is still loading', async () => {
        // No organization in context yet, and organizationLogic won't resolve it
        // synchronously — currentOrganizationId falls back to '@current' during
        // this window, which the backend 404s on.
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        initKeaTests(false)
        logic = legalDocumentsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadLegalDocumentsSuccess'])

        expect(api.legalDocumentsList).not.toHaveBeenCalled()
        expect(logic.values.legalDocuments).toEqual([])
    })
})
