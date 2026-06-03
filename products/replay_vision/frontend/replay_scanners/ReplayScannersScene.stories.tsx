import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// `@storybook/react` is not resolvable from this product's node_modules, so the
// Meta/StoryObj types are intentionally omitted — CSF reads these objects at runtime.

const alice = {
    id: 1,
    uuid: '00000000-0000-0000-0000-000000000001',
    first_name: 'Alice',
    last_name: 'Anderson',
    email: 'alice@example.com',
    hedgehog_config: null,
}
const bob = {
    id: 2,
    uuid: '00000000-0000-0000-0000-000000000002',
    first_name: 'Bob',
    last_name: 'Brown',
    email: 'bob@example.com',
    hedgehog_config: null,
}

const scanner = (overrides: Record<string, unknown>): Record<string, unknown> => ({
    id: '00000000-0000-0000-0000-00000000000a',
    name: 'Scanner',
    description: '',
    scanner_type: 'monitor',
    scanner_config: { prompt: 'Did the user struggle?' },
    query: null,
    sampling_rate: 1,
    provider: 'google',
    model: 'gemini-3-flash-preview',
    enabled: true,
    emits_signals: false,
    scanner_version: 1,
    last_swept_at: '2026-05-12T00:00:00Z',
    created_at: '2026-05-12T00:00:00Z',
    updated_at: '2026-05-12T00:00:00Z',
    created_by: null,
    ...overrides,
})

const scanners = {
    count: 4,
    next: null,
    previous: null,
    results: [
        scanner({
            id: '00000000-0000-0000-0000-00000000000a',
            name: 'Confused checkout',
            description: 'Flags sessions where the user hesitated at payment.',
            scanner_type: 'monitor',
            sampling_rate: 1,
            created_by: alice,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000b',
            name: 'Frustration tags',
            scanner_type: 'classifier',
            scanner_config: { prompt: 'Tag this session.', tags: ['rage-click', 'dead-end'], multi_label: true },
            enabled: false,
            sampling_rate: 0.25,
            created_by: bob,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000c',
            name: 'Session summary',
            scanner_type: 'summarizer',
            scanner_config: { prompt: 'Summarize this session.', length: 'medium' },
            sampling_rate: 0.05,
            created_by: alice,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000d',
            name: 'Intent score',
            scanner_type: 'scorer',
            scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
            sampling_rate: 1,
            created_by: null,
        }),
    ],
}

const quota = {
    monthly_quota: 10000,
    usage_this_month: 2400,
    remaining: 7600,
    exhausted: false,
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
}

const meta = {
    component: App,
    title: 'Scenes-App/Replay Vision',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(),
        featureFlags: [FEATURE_FLAGS.REPLAY_VISION],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/quota/': quota,
            },
        }),
    ],
}
export default meta

export const ScannersList = {}
