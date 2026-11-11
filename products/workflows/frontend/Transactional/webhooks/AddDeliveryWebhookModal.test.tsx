import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AddDeliveryWebhookModal } from './AddDeliveryWebhookModal'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

const { ToastContainer } = jest.requireActual('react-toastify')

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
                    createdBody = (await request.json()) as Record<string, any>
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

    function openModal(): void {
        render(
            <>
                <ToastContainer />
                <AddDeliveryWebhookModal />
            </>
        )
        act(() => deliveryWebhooksLogic.actions.openAddModal())
    }

    function submitUrl(url: string): void {
        fireEvent.change(screen.getByPlaceholderText('https://example.com/webhooks/email'), {
            target: { value: url },
        })
        fireEvent.click(document.querySelector('[data-attr="transactional-webhook-create"]')!)
    }

    async function startCreate(): Promise<void> {
        openModal()
        submitUrl('https://example.com/hooks')
        await waitFor(() => expect(releaseCreate).not.toBeNull())
    }

    const isDialogOpen = (): boolean => screen.queryByText('Add webhook', { selector: 'h3' }) !== null

    function tryEveryDismissal(): void {
        fireEvent.click(screen.getByText('Cancel'))
        fireEvent.keyDown(document.querySelector('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })
        fireEvent.click(document.querySelector('.LemonModal__overlay')!)
    }

    it('keeps the dialog open while the webhook is created, so the secret is shown', async () => {
        await startCreate()

        tryEveryDismissal()
        expect(isDialogOpen()).toBe(true)

        act(() => releaseCreate!([201, { id: 'new-webhook' }]))

        expect(await screen.findByText('Webhook added')).toBeInTheDocument()
        const secret = screen.getByText(/^whsec_/).textContent
        expect(secret).toEqual(createdBody!.inputs.signing_secret.value)

        fireEvent.keyDown(document.querySelector('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })
        fireEvent.click(document.querySelector('.LemonModal__overlay')!)
        expect(screen.getByText('Webhook added')).toBeInTheDocument()
        expect(document.body).toHaveTextContent(secret!)
    })

    it('creates the webhook for the events the user leaves ticked', async () => {
        openModal()
        fireEvent.click(screen.getByLabelText('Opened'))
        fireEvent.click(screen.getByLabelText('Link clicked'))
        submitUrl('https://example.com/hooks')

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

        act(() => releaseCreate!([500, { detail: 'A server error occurred.' }]))
        expect(
            await screen.findByText("Couldn't create the webhook: A server error occurred. Try again.")
        ).toBeInTheDocument()

        fireEvent.click(screen.getByText('Cancel'))
        await waitFor(() => expect(isDialogOpen()).toBe(false))
    })

    it('keeps a half-filled form open on an overlay click', () => {
        openModal()
        const input = screen.getByPlaceholderText('https://example.com/webhooks/email')
        fireEvent.change(input, { target: { value: 'https://example.com/hooks' } })

        fireEvent.click(document.querySelector('.LemonModal__overlay')!)

        expect(isDialogOpen()).toBe(true)
        expect(input).toHaveValue('https://example.com/hooks')
    })

    it('shows a bad URL as a field error, without a failure toast', async () => {
        openModal()
        submitUrl('http://example.com/hooks')

        expect(await screen.findByText('Enter a URL that starts with https://')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't create the webhook/)).not.toBeInTheDocument()
        expect(createdBody).toBeNull()
    })
})
