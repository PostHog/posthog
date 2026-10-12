import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { endpointLogic } from './endpointLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        endpoint: {
            delete: jest.fn(),
            list: jest.fn().mockResolvedValue({ results: [] }),
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

    it('opens lineage from a refused endpoint delete', async () => {
        const error = {
            detail: "Can't delete example-endpoint_v1 yet. Something else reads from it. Update or delete it first.",
            data: { extra: { node_id: 'node-7' } },
        }
        ;(api.endpoint.delete as jest.Mock).mockRejectedValue(error)
        const logic = endpointLogic()
        logic.mount()
        router.actions.push(urls.endpoint('example-endpoint'))

        logic.actions.deleteEndpoint('example-endpoint')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toContain(urls.endpoint('example-endpoint'))
        const options = (lemonToast.error as jest.Mock).mock.calls[0][1] as {
            button?: { label: string; action: () => void }
        }
        expect(lemonToast.error).toHaveBeenCalledWith(error.detail, expect.any(Object))
        expect(options.button?.label).toBe('Open lineage')
        options.button?.action()
        expect(router.values.location.pathname).toContain(urls.nodeDetail('node-7', 'lineage'))
    })

    it('returns to the endpoint list after a successful delete', async () => {
        ;(api.endpoint.delete as jest.Mock).mockResolvedValue(undefined)
        const logic = endpointLogic()
        logic.mount()
        router.actions.push(urls.endpoint('example-endpoint'))

        logic.actions.deleteEndpoint('example-endpoint')
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.success).toHaveBeenCalledWith('Endpoint deleted')
        expect(router.values.location.pathname).toContain(urls.endpoints())
    })
})
