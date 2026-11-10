import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { AvailableFeature, StartupProgramLabel } from '~/types'

const SUBMITTER = {
    first_name: 'Ada',
    email: 'ada@acme.example',
}

const LEGAL_DOCUMENT_LIST = [
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb501',
        document_type: 'BAA',
        company_name: 'Acme Health, Inc.',
        representative_email: 'ada@acme.example',
        status: 'signed',
        signed_pdf_stored: true,
        created_by: SUBMITTER,
        created_at: '2026-04-10T12:00:00Z',
    },
    {
        id: '0187c22c-06d9-0000-34fe-daa2e2afb502',
        document_type: 'DPA',
        company_name: 'Acme Health, Inc.',
        representative_email: 'ada@acme.example',
        status: 'submitted_for_signature',
        signed_pdf_stored: false,
        created_by: SUBMITTER,
        created_at: '2026-04-20T15:30:00Z',
    },
]

/** Startup credits do not cover a BAA, even when the organization has the entitlement. */
const startupProgramBilling = (label: StartupProgramLabel): Record<string, unknown> => ({
    products: [],
    has_active_subscription: true,
    startup_program_label: label,
})

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

const withBaaEntitlement: Decorator = (Story) => {
    useAvailableFeatures([AvailableFeature.HIPAA_BAA])
    return <Story />
}

/**
 * Landing screen at `/legal` with two prior submissions — one signed BAA and
 * one DPA waiting for counter-signature — so the two status tags are both
 * visible alongside the download link.
 */
export const LegalDocumentsList: Story = {}

/**
 * New-document page for an organization with the BAA entitlement.
 */
export const NewBAA: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('BAA'),
    },
    decorators: [
        withBaaEntitlement,
        mswDecorator({
            get: {
                '/api/billing/': {
                    products: [],
                    has_active_subscription: true,
                },
            },
        }),
    ],
}

/**
 * New-document page for a BAA when the org is on an active addon trial. The
 * billing payload includes a top-level `trial` block targeting `boost`, so the
 * paywall banner swaps to the trial-specific copy that instructs the user to
 * cancel the trial and subscribe before generating the BAA.
 */
export const NewBAATrial: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('BAA'),
    },
    decorators: [
        withBaaEntitlement,
        mswDecorator({
            get: {
                '/api/billing/': {
                    products: [],
                    trial: {
                        type: 'standard',
                        status: 'active',
                        target: 'boost',
                        expires_at: '2026-06-15T00:00:00Z',
                    },
                    has_active_subscription: false,
                },
            },
        }),
    ],
}

/**
 * New-document page for a BAA when the org is on a sales-managed Enterprise
 * trial. The billing page hides the cancel-trial button for these, so the
 * banner directs users to contact billing support instead of cancelling on
 * billing.
 */
export const NewBAAEnterpriseTrial: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('BAA'),
    },
    decorators: [
        withBaaEntitlement,
        mswDecorator({
            get: {
                '/api/billing/': {
                    products: [],
                    trial: {
                        type: 'standard',
                        status: 'active',
                        target: 'enterprise',
                        expires_at: '2026-06-15T00:00:00Z',
                    },
                    has_active_subscription: false,
                },
            },
        }),
    ],
}

/**
 * Landing screen at `/legal` for an organization on the Startup program with no
 * BAA yet. The organization has the entitlement, but the BAA menu item is
 * disabled because startup credits do not cover a BAA.
 */
export const ListStartupProgram: Story = {
    decorators: [
        withBaaEntitlement,
        mswDecorator({
            get: {
                '/api/organizations/:org_id/legal_documents': EMPTY_PAGINATED_RESPONSE,
                '/api/billing/': startupProgramBilling(StartupProgramLabel.Startup),
            },
        }),
    ],
}

/**
 * New-document page for a BAA when the org is on the Startup program and has no
 * BAA yet. The banner replaces the paywall copy and the submit button is
 * disabled by the startup block rather than by an existing document.
 */
export const NewBAAStartupProgram: Story = {
    parameters: {
        pageUrl: urls.legalDocumentNew('BAA'),
    },
    decorators: [
        withBaaEntitlement,
        mswDecorator({
            get: {
                '/api/organizations/:org_id/legal_documents': EMPTY_PAGINATED_RESPONSE,
                '/api/billing/': startupProgramBilling(StartupProgramLabel.Startup),
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
