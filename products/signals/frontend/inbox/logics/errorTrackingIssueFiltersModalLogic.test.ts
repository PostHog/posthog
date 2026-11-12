import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../inboxAnalytics'
import { SignalSourceConfig, SignalSourceProduct, SignalSourceType } from '../types'
import { errorTrackingIssueFiltersModalLogic } from './errorTrackingIssueFiltersModalLogic'

const PRODUCTION = { key: '$environment', type: 'event', operator: 'exact', value: ['production'] }

function errorTrackingConfig(
    id: string,
    sourceType: SignalSourceType,
    config: Record<string, any>
): SignalSourceConfig {
    return {
        id,
        source_product: SignalSourceProduct.ErrorTracking,
        source_type: sourceType,
        enabled: false,
        config,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
        status: null,
    }
}

const configs = [
    errorTrackingConfig('created', SignalSourceType.IssueCreated, {
        steering: 'Skip bots',
        issue_filters: { properties: [PRODUCTION] },
    }),
    errorTrackingConfig('reopened', SignalSourceType.IssueReopened, { issue_filters: { properties: [PRODUCTION] } }),
    errorTrackingConfig('spiking', SignalSourceType.IssueSpiking, { issue_filters: { properties: [PRODUCTION] } }),
]

describe('errorTrackingIssueFiltersModalLogic', () => {
    let logic: ReturnType<typeof errorTrackingIssueFiltersModalLogic.build>
    let patches: { id: string; body: Record<string, any> }[]
    let failingId: string | null
    let onClose: jest.Mock
    let captureSpy: jest.SpyInstance
    let successToast: jest.SpyInstance
    let errorToast: jest.SpyInstance

    beforeEach(() => {
        patches = []
        failingId = null
        captureSpy = jest.spyOn(posthog, 'capture')
        successToast = jest.spyOn(lemonToast, 'success')
        errorToast = jest.spyOn(lemonToast, 'error')
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: configs, count: configs.length, next: null, previous: null },
                ],
                '/api/environments/:team_id/quick_filters/': () => [200, { results: [] }],
                '/api/projects/:team_id/quick_filters/': () => [200, { results: [] }],
            },
            patch: {
                '/api/projects/:team_id/signals/source_configs/:id/': async ({ request, params }) => {
                    const body = (await request.json()) as Record<string, any>
                    patches.push({ id: String(params.id), body })
                    const existing = configs.find((config) => config.id === params.id)!
                    return String(params.id) === failingId
                        ? [500, { detail: 'Unable to save source settings.' }]
                        : [200, { ...existing, config: { ...existing.config, ...body.config_set } }]
                },
            },
        })
        initKeaTests()
        onClose = jest.fn()
        logic = errorTrackingIssueFiltersModalLogic({ sourceConfigs: configs, onClose })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function filterEvents(): Record<string, any>[] {
        return captureSpy.mock.calls
            .filter(([event]) => event === INBOX_EVENTS.SOURCE_FILTERS_CHANGED)
            .map(([, properties]) => properties)
    }

    it('saves one filter to every error tracking row without touching enabled or steering', async () => {
        logic.actions.setSeverity('critical')

        await expectLogic(logic, () => logic.actions.saveFilters()).toFinishAllListeners()

        const expected = {
            config_set: {
                issue_filters: {
                    properties: [
                        PRODUCTION,
                        { key: 'severity', type: 'event', operator: 'exact', value: ['critical'] },
                    ],
                },
            },
        }
        expect(patches).toEqual(configs.map((config) => ({ id: config.id, body: expected })))
        expect(onClose).toHaveBeenCalled()
        expect(filterEvents()).toEqual([expect.objectContaining({ selected_count: 2, success: true })])
    })

    it('does not report success when one row fails to save', async () => {
        failingId = 'reopened'

        await expectLogic(logic, () => logic.actions.saveFilters()).toFinishAllListeners()

        expect(patches.map((patch) => patch.id)).toEqual(['created', 'reopened', 'spiking'])
        expect(onClose).not.toHaveBeenCalled()
        expect(successToast).not.toHaveBeenCalled()
        expect(errorToast).toHaveBeenCalled()
        expect(logic.values.saving).toBe(false)
        expect(filterEvents()).toEqual([expect.objectContaining({ success: false })])
    })

    it('clears the filter from every row', async () => {
        await expectLogic(logic, () => logic.actions.clearFilters()).toFinishAllListeners()

        expect(patches.map((patch) => patch.body)).toEqual(configs.map(() => ({ config_remove: ['issue_filters'] })))
        expect(filterEvents()).toEqual([expect.objectContaining({ selected_count: 0, reads_everything: true })])
    })
})
