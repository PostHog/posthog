import { Meta, StoryObj } from '@storybook/react'
import { userEvent, waitFor } from '@storybook/testing-library'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const SUBMITTER = {
    first_name: 'Ada',
    email: 'ada@acme.example',
}

const LEGAL_DOCUMENT_LIST = [
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb501',
        document_type: 'BAA',
        company_name: 'Acme Health, Inc.',
        representative_name: 'Ada Lovelace',
        representative_email: 'ada@acme.example',
        status: 'signed',
        signed_document_url: 'https://app.pandadoc.com/s/acme-baa-signed.pdf',
        created_by: SUBMITTER,
        created_at: '2026-04-10T12:00:00Z',
    },
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb502',
        document_type: 'DPA',
        company_name: 'Acme Health, Inc.',
        representative_name: 'Ada Lovelace',
        representative_email: 'ada@acme.example',
        status: 'submitted_for_signature',
        signed_document_url: '',
        created_by: SUBMITTER,
        created_at: '2026-04-20T15:30:00Z',
    },
]

/**
 * Mounts the legal documents scene(s) against a mocked API. A single shared
 * decorator is enough because the list endpoint is the only API call the
 * scenes make up-front — the create path is only hit after `Send for signature`.
 */
const meta: Meta = {
    component: App,
    title: 'Scenes-App/Legal documents',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-21',
        pageUrl: urls.legalDocuments(),
        featureFlags: ['legal-documents'],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:org_id/legal_documents': {
                    count: LEGAL_DOCUMENT_LIST.length,
                    results: LEGAL_DOCUMENT_LIST,
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

/**
 * Landing screen at `/legal` with two prior submissions — one signed BAA and
 * one DPA waiting for counter-signature — so the two status tags are both
 * visible alongside the download link.
 */
export const LegalDocumentsList: Story = {}

/**
 * New-document page for a BAA. Mocks the billing endpoint so the scene sees an
 * active `boost` add-on and the form isn't gated behind the paywall banner.
 */
export const NewBAA: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('BAA'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/billing/': {
                    products: [
                        {
                            type: 'platform_and_support',
                            addons: [{ type: 'boost', subscribed: true }],
                        },
                    ],
                    has_active_subscription: true,
                },
            },
        }),
    ],
}

/**
 * New-document page for a DPA in the default "pretty" mode (legally binding,
 * rendered with a color PostHog logo at the top).
 */
export const NewDPAPretty: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('DPA'),
    },
}

/**
 * Serif "lawyer" mode. Click the matching radio once the scene has mounted.
 */
export const NewDPALawyer: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('DPA'),
    },
    play: async ({ canvasElement }) => {
        await selectDpaMode(canvasElement, 'lawyer')
    },
}

/**
 * Fairy-tale mode — illustrated, Computer Modern body, custom "Fairytale" title font.
 * Preview only; the submit button stays disabled.
 */
export const NewDPAFairytale: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('DPA'),
    },
    play: async ({ canvasElement }) => {
        await selectDpaMode(canvasElement, 'fairytale')
    },
}

/**
 * Taylor Swift "Data Dance" mode. Preview only; submit stays disabled.
 */
export const NewDPATSwift: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('DPA'),
    },
    play: async ({ canvasElement }) => {
        await selectDpaMode(canvasElement, 'tswift')
    },
}

/**
 * Clicks the matching radio input for a DPA mode. Waits until the scene has
 * rendered before trying so we don't race the async scene import.
 */
async function selectDpaMode(
    canvasElement: HTMLElement,
    mode: 'pretty' | 'lawyer' | 'fairytale' | 'tswift'
): Promise<void> {
    const radio = await waitFor(
        () => {
            const input = canvasElement.querySelector<HTMLInputElement>(`input[type="radio"][value="${mode}"]`)
            if (!input) {
                throw new Error(`DPA mode radio for "${mode}" not yet rendered`)
            }
            return input
        },
        { timeout: 3000 }
    )
    await userEvent.click(radio)
}
