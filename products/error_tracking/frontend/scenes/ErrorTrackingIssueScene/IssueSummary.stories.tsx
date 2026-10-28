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
                regenerating={false}
                feedback={null}
                onRegenerate={noop}
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

export const Generating: Story = {
    render: () => render({ view: 'generating', summary: null }),
    // The skeleton is the state under test, so the runner must not wait for it to go away.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const TimedOut: Story = { render: () => render({ view: 'timed_out', summary: null }) }

export const Failed: Story = { render: () => render({ view: 'failed', summary: null }) }
