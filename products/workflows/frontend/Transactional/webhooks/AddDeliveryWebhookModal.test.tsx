import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AddDeliveryWebhookModal } from './AddDeliveryWebhookModal'
import { deliveryWebhooksLogic } from './deliveryWebhooksLogic'

const { ToastContainer } = jest.requireActual('react-toastify')

type CreateResponse = [number, Record<string, any>]

describe('AddDeliveryWebhookModal', () => {
    let releaseCreate: ((response: CreateResponse) => void) | null
    let createdBody: Record<string, any> | null
    let templatesLoad: 'fails' | 'denied' | 'succeeds'

    beforeEach(() => {
        releaseCreate = null
        createdBody = null
        templatesLoad = 'succeeds'
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': () =>
                    templatesLoad === 'fails'
                        ? [500, { detail: 'A server error occurred.' }]
                        : templatesLoad === 'denied'
                          ? [403, { detail: 'You do not have permission to perform this action.' }]
                          : [
                                200,
                                {
                                    count: 1,
                                    next: null,
                                    results: [
                                        {
                                            id: 'template-1',
                                            name: 'Receipt',
                                            transactional_hog_flow_id: 'flow-1',
                                            has_draft: false,
                                        },
                                    ],
                                },
                            ],
            },
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

    it('closes only the email picker on Escape, keeping the dialog and the typed URL', async () => {
        openModal()
        const url = screen.getByPlaceholderText('https://example.com/webhooks/email')
        fireEvent.change(url, { target: { value: 'https://example.com/hooks' } })
        const picker = screen.getByPlaceholderText('All transactional emails')
        fireEvent.click(picker)
        expect(await screen.findByText('Receipt')).toBeInTheDocument()

        fireEvent.keyDown(picker, { key: 'Escape', keyCode: 27 })

        await waitFor(() => expect(screen.queryByText('Receipt')).not.toBeInTheDocument())
        expect(isDialogOpen()).toBe(true)
        expect(url).toHaveValue('https://example.com/hooks')
    })

    it('says when the transactional emails fail to load, and loads them again on retry', async () => {
        templatesLoad = 'fails'
        openModal()

        const banner = (
            await screen.findByText(
                "Couldn't load your transactional emails: A server error occurred. Try again, or leave the field empty to get updates for all of them."
            )
        ).closest('.LemonBanner')!
        expect(screen.queryByText(/No transactional emails yet/)).not.toBeInTheDocument()
        expect(document.querySelector('.Toastify__toast')).toBeNull()

        templatesLoad = 'succeeds'
        fireEvent.click(within(banner as HTMLElement).getAllByText('Try again')[0])
        fireEvent.click(screen.getByPlaceholderText('All transactional emails'))

        expect(await screen.findByText('Receipt')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't load your transactional emails/)).not.toBeInTheDocument()
    })

    it('says which access is missing when the user cannot read email templates', async () => {
        templatesLoad = 'denied'
        openModal()

        expect(await screen.findByText(/You don't have access to this project's email templates/)).toBeInTheDocument()
        expect(screen.queryByText('Try again')).not.toBeInTheDocument()
    })

    it('shows a bad URL as a field error, without a failure toast', async () => {
        openModal()
        submitUrl('http://example.com/hooks')

        expect(await screen.findByText('Enter a URL that starts with https://')).toBeInTheDocument()
        expect(screen.queryByText(/Couldn't create the webhook/)).not.toBeInTheDocument()
        expect(createdBody).toBeNull()
    })
})
