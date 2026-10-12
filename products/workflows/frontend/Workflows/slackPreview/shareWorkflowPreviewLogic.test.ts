import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { hogFlowsSharePreviewToSlack } from 'products/workflows/frontend/generated/api'

import type { HogFlow } from '../hogflows/types'
import { renderEmailPreviewBase64 } from './renderEmailPreview'
import { shareWorkflowPreviewLogic } from './shareWorkflowPreviewLogic'

jest.mock('./renderEmailPreview', () => ({ renderEmailPreviewBase64: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({ hogFlowsSharePreviewToSlack: jest.fn() }))

const render = renderEmailPreviewBase64 as jest.MockedFunction<typeof renderEmailPreviewBase64>
const share = hogFlowsSharePreviewToSlack as jest.MockedFunction<typeof hogFlowsSharePreviewToSlack>

const ONE_MEGABYTE_IN_BASE64 = Math.ceil((1024 * 1024 * 4) / 3)
const SAVED_AT = '2026-10-01T09:00:00Z'

const workflow = {
    id: 'workflow-1',
    name: 'Onboarding drip',
    actions: [
        { id: 'trigger', name: 'Trigger', type: 'trigger', config: { type: 'event' } },
        {
            id: 'welcome',
            name: 'Welcome',
            type: 'function_email',
            config: { inputs: { email: { value: { subject: 'Welcome to Hedgebox', html: '<p>Hi</p>' } } } },
        },
    ],
    edges: [{ from: 'trigger', to: 'welcome', type: 'continue' }],
} as unknown as HogFlow

describe('shareWorkflowPreviewLogic', () => {
    let logic: ReturnType<typeof shareWorkflowPreviewLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 10, kind: 'slack', config: { scope: 'chat:write,files:write' } }],
                },
            },
        })
        initKeaTests()
        render.mockReset()
        share.mockReset()
        logic = shareWorkflowPreviewLogic({ id: 'workflow-1' })
        logic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
        logic.actions.openModal(workflow, SAVED_AT)
        logic.actions.setIntegrationId(10)
        logic.actions.setChannel('C0PREVIEW|#workflow-previews')
    })

    afterEach(() => logic.unmount())

    it.each([
        ['a PNG within the limit', ['small-png'], 'small-png', 1],
        [
            'a JPEG when the PNG is over the limit',
            ['p'.repeat(ONE_MEGABYTE_IN_BASE64 + 8), 'small-jpeg'],
            'small-jpeg',
            2,
        ],
    ])('shares %s', async (_name, renders, expectedImage, expectedRenders) => {
        renders.forEach((image) => render.mockResolvedValueOnce(image))
        share.mockResolvedValue({ channel: 'C0PREVIEW', thread_ts: null })

        await expectLogic(logic, () => logic.actions.submit()).toDispatchActions(['submitSuccess'])

        expect(render).toHaveBeenCalledTimes(expectedRenders)
        expect(share.mock.calls[0][2]).toMatchObject({
            workflow_saved_at: SAVED_AT,
            emails: [{ action_id: 'welcome', image_base64: expectedImage }],
        })
    })

    it('keeps the modal open and posts nothing when an email is over the limit in both formats', async () => {
        render.mockResolvedValue('p'.repeat(ONE_MEGABYTE_IN_BASE64 + 8))

        await expectLogic(logic, () => logic.actions.submit()).toDispatchActions([
            (action) => action.type === logic.actionTypes.submitFailure && action.payload.reason === 'image_too_large',
        ])
        expect(logic.values.isOpen).toBe(true)
        expect(share).not.toHaveBeenCalled()
    })
})
