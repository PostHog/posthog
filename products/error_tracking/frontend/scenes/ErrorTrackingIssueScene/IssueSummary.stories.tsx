import type { Meta, StoryObj } from '@storybook/react'

import type { ErrorTrackingStoredIssueSummaryApi } from '../../generated/api.schemas'
import { IssueSummarySection, IssueSummarySectionProps } from './IssueSummary'

const meta: Meta<typeof IssueSummarySection> = {
    title: 'Scenes-App/ErrorTracking/IssueSummary',
    component: IssueSummarySection,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-10-22' },
}
export default meta

type Story = StoryObj<typeof IssueSummarySection>

const SUMMARY: ErrorTrackingStoredIssueSummaryApi = {
    what_happened: 'A TypeError is thrown in the checkout page when the cart total is read before the cart has loaded.',
    likely_cause: 'The cart request can finish after the first render when the session token is refreshed.',
    who_is_affected: 'About 40 signed-in users a day, mostly on Safari, in the last 7 days.',
    suggested_next_step: 'Check that the checkout page waits for the cart request before it reads the total.',
    category: 'own_code',
    model: 'gpt-4.1-mini',
    generated_at: '2026-10-20T09:00:00Z',
    checked_at: '2026-10-20T09:00:00Z',
}

const noop = (): void => {}

function render(props: Partial<IssueSummarySectionProps>, width: 'narrow' | 'wide' = 'narrow'): JSX.Element {
    return (
        <div className={width === 'wide' ? 'w-[720px] border' : 'w-[520px] border'}>
            <IssueSummarySection
                view="ready"
                summary={SUMMARY}
                feedback={null}
                open
                canManageAiSettings
                loading={false}
                onToggle={noop}
                onRetry={noop}
                onFeedback={noop}
                {...props}
            />
        </div>
    )
}

export const Ready: Story = { render: () => render({}) }

export const ReadyWide: Story = { render: () => render({}, 'wide') }

export const ReadyWithoutLikelyCause: Story = {
    render: () => render({ summary: { ...SUMMARY, likely_cause: '' }, feedback: 'good' }),
}

export const Failed: Story = { render: () => render({ view: 'failed', summary: null }) }

export const Closed: Story = { render: () => render({ open: false }) }

// Each reason a summary is missing is one line. Snapshots of these add nothing the Failed row does not cover.
const NO_SNAPSHOT = { testOptions: { snapshotBrowsers: [] } }

export const Writing: Story = {
    render: () => render({ view: 'writing', summary: null }),
    parameters: NO_SNAPSHOT,
}

export const NotGenerated: Story = {
    render: () => render({ view: 'not_generated', summary: null }),
    parameters: NO_SNAPSHOT,
}

export const AiNotApproved: Story = {
    render: () => render({ view: 'ai_not_approved', summary: null }),
    parameters: NO_SNAPSHOT,
}

export const AiNotApprovedForMember: Story = {
    render: () => render({ view: 'ai_not_approved', summary: null, canManageAiSettings: false }),
    parameters: NO_SNAPSHOT,
}

export const Restricted: Story = {
    render: () => render({ view: 'restricted', summary: null }),
    parameters: NO_SNAPSHOT,
}
