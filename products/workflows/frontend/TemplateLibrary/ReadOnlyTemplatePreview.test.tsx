import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ReadOnlyTemplatePreview } from './ReadOnlyTemplatePreview'

const SENDER = {
    id: 5,
    kind: 'email',
    display_name: 'Hedgebox',
    config: { email: 'hello@example.com', name: 'Hedgebox', reply_to: 'support@example.com' },
}

function email(overrides: Partial<EmailTemplate>): EmailTemplate {
    return { subject: 'Welcome', html: '<p>Hi</p>', text: 'Hi', design: null, from: '', to: '', ...overrides }
}

describe('ReadOnlyTemplatePreview', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/integrations/': { count: 1, results: [SENDER] } } })
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([
        {
            description: "the template's own name, address and reply-to",
            template: email({
                from: { integrationId: 5, email: 'billing@example.com', name: 'Billing' },
                replyTo: 'help@example.com',
            }),
            name: 'Billing',
            address: '<billing@example.com>',
            replyTo: 'Replies go to help@example.com',
        },
        {
            description: "the sender's defaults when the template sets none",
            template: email({ from: { integrationId: 5 } }),
            name: 'Hedgebox',
            address: '<hello@example.com>',
            replyTo: 'Replies go to support@example.com',
        },
    ])('shows who the email comes from with $description', async ({ template, name, address, replyTo }) => {
        render(<ReadOnlyTemplatePreview email={template} />)

        expect(await screen.findByText(name)).toBeInTheDocument()
        expect(screen.getByText(address)).toBeInTheDocument()
        expect(screen.getByText(replyTo)).toBeInTheDocument()
    })

    it('says when the template has no sender', async () => {
        render(<ReadOnlyTemplatePreview email={email({ from: '' })} />)

        expect(await screen.findByText('No sender set')).toBeInTheDocument()
    })

    it('says the sender could not load when the integrations request fails', async () => {
        useMocks({ get: { '/api/projects/:team_id/integrations/': [500, { detail: 'Server error' }] } })

        render(<ReadOnlyTemplatePreview email={email({ from: { integrationId: 5 } })} />)

        expect(await screen.findByText("Couldn't load the sender. Refresh the page to try again.")).toBeInTheDocument()
    })
})
