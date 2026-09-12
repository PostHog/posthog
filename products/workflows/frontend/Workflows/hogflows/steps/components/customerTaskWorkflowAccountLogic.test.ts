import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import * as api from 'products/customer_analytics/frontend/generated/api'

import { customerTaskWorkflowAccountLogic } from './customerTaskWorkflowAccountLogic'

jest.mock('products/customer_analytics/frontend/generated/api')

const accountsList = jest.mocked(api.accountsList)
const accountsRetrieve = jest.mocked(api.accountsRetrieve)
const accountId = '11111111-1111-4111-8111-111111111111'

describe('customerTaskWorkflowAccountLogic', () => {
    let logic: ReturnType<typeof customerTaskWorkflowAccountLogic.build>

    beforeEach(() => {
        initKeaTests()
        // The saved account is absent from the first page, which is what sends the loader to
        // accountsRetrieve. Any team with more accounts than the page limit hits this on every open.
        accountsList.mockResolvedValue({ results: [] } as any)
        logic = customerTaskWorkflowAccountLogic({ id: 'test', projectId: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // The picker only tells someone their saved account is unavailable, and to replace it, when
    // `failed` is false. That advice is safe for a deleted account and wrong for a transient error.
    it.each([
        ['a deleted account as unavailable', new ApiError(undefined, 404), false],
        ['a server error as retryable', new ApiError(undefined, 500), true],
        ['a permission failure as retryable', new ApiError(undefined, 403), true],
        ['a network failure as retryable', new Error('Failed to fetch'), true],
    ])('reports %s', async (_name, error, failed) => {
        accountsRetrieve.mockRejectedValue(error)
        logic.actions.loadChoices({ query: '', accountId })
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ choices: { options: [], failed } })
    })

    it('keeps a saved account that resolves outside the first page', async () => {
        accountsRetrieve.mockResolvedValue({ id: accountId, name: 'Example account' } as any)
        logic.actions.loadChoices({ query: '', accountId })
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ choices: { options: [{ key: accountId, label: 'Example account' }], failed: false } })
    })
})
