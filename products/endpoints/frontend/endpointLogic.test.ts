import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointLogic } from './endpointLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        endpoint: {
            update: jest.fn(),
        },
    },
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

describe('endpointLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('shows the API detail when an endpoint update fails', async () => {
        ;(api.endpoint.update as jest.Mock).mockRejectedValue({
            detail: 'Cannot materialize endpoint. Reason: The referenced table does not exist.',
        })
        const logic = endpointLogic()
        logic.mount()

        logic.actions.updateEndpoint('example-endpoint', { is_materialized: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith(
            'Failed to update endpoint: Cannot materialize endpoint. Reason: The referenced table does not exist.'
        )
    })
})
