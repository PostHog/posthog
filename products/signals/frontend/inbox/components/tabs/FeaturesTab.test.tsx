import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

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
        render(<FeatureDiscoveryBanner run={DISCOVERY_RUN} />)

        expect(screen.getByRole('link', { name: 'View task logs' })).toHaveAttribute(
            'href',
            expect.stringContaining(`/tasks/${DISCOVERY_RUN.task_id}`)
        )
    })
})
