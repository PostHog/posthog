import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { emailSetupModalLogic } from './emailSetupModalLogic'

describe('emailSetupModalLogic', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/environments/:team_id/integrations': { results: [] } },
            post: {
                '/api/environments/:team_id/integrations/:id/email/verify': { status: 'pending', dnsRecords: [] },
            },
        })
        initKeaTests()
    })

    // A legacy or hand-edited integration row can hold a config without an `email` key. An unguarded
    // read of it threw, and the error escaped to the app error boundary, so the whole scene went
    // blank instead of the modal opening.
    it('keeps the form defaults when the integration config has no email', async () => {
        const logic = emailSetupModalLogic({
            integration: { id: 1, kind: 'email', config: {} } as IntegrationType,
            onComplete: () => {},
            onClose: () => {},
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            domain: '',
            emailSender: expect.objectContaining({ email: '', name: '', provider: 'ses' }),
        })
    })
})
