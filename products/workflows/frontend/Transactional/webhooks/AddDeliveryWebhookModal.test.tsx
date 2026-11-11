import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AddDeliveryWebhookModal } from './AddDeliveryWebhookModal'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

type CreateResponse = [number, Record<string, any>]

describe('AddDeliveryWebhookModal', () => {
    let releaseCreate: ((response: CreateResponse) => void) | null
    let createdBody: Record<string, any> | null

    beforeEach(() => {
        releaseCreate = null
        createdBody = null
        useMocks({
            post: {
                '/api/projects/:team_id/hog_functions/': async ({ request }) => {
                    createdBody = await request.json()
                    return new Promise<CreateResponse>((resolve) => {
                        releaseCreate = resolve
                    })
                },
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
        act(() => deliveryWebhooksLogic.actions.openAddModal())
        fireEvent.change(screen.getByPlaceholderText('https://example.com/webhooks/email'), {
            target: { value: 'https://example.com/hooks' },
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
        expect(screen.getByText('Add webhook', { selector: 'h3' })).toBeInTheDocument()

        act(() => releaseCreate!([201, { id: 'new-webhook' }]))

        expect(await screen.findByText('Webhook added')).toBeInTheDocument()
        const secret = deliveryWebhooksLogic.values.createdSecret
        expect(secret).toMatch(/^whsec_/)

        // The secret is shown once, so only "Done" may close this view.
        fireEvent.keyDown(document.querySelector('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })
        fireEvent.click(document.querySelector('.LemonModal__overlay')!)
        expect(screen.getByText('Webhook added')).toBeInTheDocument()
        expect(document.body).toHaveTextContent(secret!)
    })

    it('creates the webhook for the events the user leaves ticked', async () => {
        render(<AddDeliveryWebhookModal />)
        act(() => deliveryWebhooksLogic.actions.openAddModal())

        fireEvent.change(screen.getByPlaceholderText('https://example.com/webhooks/email'), {
            target: { value: 'https://example.com/hooks' },
        })
        fireEvent.click(screen.getByLabelText('Opened'))
        fireEvent.click(screen.getByLabelText('Link clicked'))
        fireEvent.click(document.querySelector('[data-attr="transactional-webhook-create"]')!)

        await waitFor(() => expect(createdBody).not.toBeNull())
        expect(createdBody!.inputs.url.value).toEqual('https://example.com/hooks')
        expect(createdBody!.filters.events.map(({ id }: { id: string }) => id)).toEqual([
            '$workflows_email_sent',
            '$workflows_email_delivered',
            '$workflows_email_bounced',
            '$workflows_email_blocked',
            '$workflows_email_failed',
        ])
    })

    it('lets the user close the dialog again after a failed create', async () => {
        await startCreate()

        act(() => releaseCreate!([500, { detail: 'Server error' }]))
        await waitFor(() => expect(deliveryWebhooksLogic.values.isWebhookFormSubmitting).toBe(false))

        fireEvent.click(screen.getByText('Cancel'))
        expect(deliveryWebhooksLogic.values.isAddModalOpen).toBe(false)
    })
})
