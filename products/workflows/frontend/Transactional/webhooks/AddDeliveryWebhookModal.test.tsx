import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AddDeliveryWebhookModal } from './AddDeliveryWebhookModal'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

type CreateResponse = [number, Record<string, any>]

describe('AddDeliveryWebhookModal', () => {
    let releaseCreate: ((response: CreateResponse) => void) | null

    beforeEach(() => {
        releaseCreate = null
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/template-webhook/': {
                    id: 'template-webhook',
                    code: 'fetch(inputs.url, {})',
                    inputs_schema: [{ key: 'url', type: 'string' }],
                },
            },
            post: {
                '/api/projects/:team_id/hog_functions/': () =>
                    new Promise<CreateResponse>((resolve) => {
                        releaseCreate = resolve
                    }),
            },
        })
        initKeaTests()
        deliveryWebhooksLogic.mount()
    })

    afterEach(() => {
        cleanup()
        deliveryWebhooksLogic.unmount()
    })

    async function startCreate(): Promise<void> {
        render(<AddDeliveryWebhookModal />)
        act(() => {
            deliveryWebhooksLogic.actions.openAddModal()
            deliveryWebhooksLogic.actions.setWebhookFormValue('url', 'https://example.com/hooks')
        })
        fireEvent.click(document.querySelector('[data-attr="transactional-webhook-create"]')!)
        await waitFor(() => expect(releaseCreate).not.toBeNull())
    }

    function tryEveryDismissal(): void {
        fireEvent.click(screen.getByText('Cancel'))
        fireEvent.keyDown(document.querySelector('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })
        fireEvent.click(document.querySelector('.LemonModal__overlay')!)
    }

    it('keeps the dialog open while the webhook is created, so the secret is shown', async () => {
        await startCreate()

        tryEveryDismissal()
        expect(deliveryWebhooksLogic.values.isAddModalOpen).toBe(true)

        act(() => releaseCreate!([201, { id: 'new-webhook' }]))

        expect(await screen.findByText('Webhook added')).toBeInTheDocument()
        const secret = deliveryWebhooksLogic.values.createdSecret
        expect(secret).toMatch(/^whsec_/)
        expect(document.body).toHaveTextContent(secret!)
    })

    it('lets the user close the dialog again after a failed create', async () => {
        await startCreate()

        act(() => releaseCreate!([500, { detail: 'Server error' }]))
        await waitFor(() => expect(deliveryWebhooksLogic.values.isWebhookFormSubmitting).toBe(false))

        fireEvent.click(screen.getByText('Cancel'))
        expect(deliveryWebhooksLogic.values.isAddModalOpen).toBe(false)
    })
})
