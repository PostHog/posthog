import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { codeEmailLogic } from './codeEmailLogic'

describe('codeEmailLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_code_emails/gone-id/': () => [404, { detail: 'Not found.' }],
            },
        })
        initKeaTests()
    })

    it('resolves an email that no longer exists to null, so the page shows not found', async () => {
        const logic = codeEmailLogic({ id: 'gone-id' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.codeEmail).toBeNull()
        logic.unmount()
    })
})
