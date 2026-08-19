import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import type { InboxFeatureDiscoveryRunApi } from '../../../generated/api.schemas'
import { FeatureDiscoveryBanner } from './FeaturesTab'

const DISCOVERY_RUN: InboxFeatureDiscoveryRunApi = {
    id: '019c0000-0000-7000-8000-000000000001',
    repository: 'PostHog/posthog',
    focus: '',
    discovery_status: 'running',
    discovered_count: 0,
    error: '',
    task_id: '019c0000-0000-7000-8000-000000000002',
    created_at: '2026-08-19T08:00:00Z',
    updated_at: '2026-08-19T08:01:00Z',
}

describe('FeatureDiscoveryBanner', () => {
    afterEach(cleanup)

    it('links to the task logs after the discovery agent starts', () => {
        const { container } = render(<FeatureDiscoveryBanner run={DISCOVERY_RUN} />)
        const taskLogLinks = container.querySelectorAll('[data-attr="feature-discovery-view-task-logs"]')

        expect(taskLogLinks.length).toBeGreaterThan(0)
        taskLogLinks.forEach((taskLogLink) =>
            expect(taskLogLink).toHaveAttribute('href', expect.stringContaining(`/tasks/${DISCOVERY_RUN.task_id}`))
        )
    })

    it('shows why task logs are unavailable before the discovery agent starts', () => {
        const { container } = render(
            <FeatureDiscoveryBanner run={{ ...DISCOVERY_RUN, discovery_status: 'queued', task_id: null }} />
        )
        const taskLogButtons = container.querySelectorAll('[data-attr="feature-discovery-view-task-logs"]')

        expect(taskLogButtons.length).toBeGreaterThan(0)
        taskLogButtons.forEach((taskLogButton) => expect(taskLogButton).toHaveAttribute('aria-disabled', 'true'))
    })
})
