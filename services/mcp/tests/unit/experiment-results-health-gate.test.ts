import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { getResultsHandler } from '@/tools/experiments/getResults'
import type { Context } from '@/tools/types'

vi.mock('@/lib/posthog/flags', () => ({ isFeatureFlagEnabled: vi.fn() }))

// The configuration checks reach agents only where the flag shows the health panel in the app. Without the
// gate, a customer's agent reports findings the customer cannot see; a failed read must not fail the results.
describe('experiment-results-get configuration health gate', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    const exposures = {
        kind: 'ExperimentExposureQuery',
        timeseries: [],
        total_exposures: {},
        date_range: { date_from: '2026-01-01T00:00:00Z', date_to: null },
        health_findings: [],
        health_checks: [{ key: 'srm', name: 'Sample ratio mismatch', reason: null, status: 'passed' }],
    }

    const configHealth = {
        findings: [
            {
                actions: ['add_primary_metric'],
                check: 'no_metric',
                code: 'no_metric',
                detail: 'detail',
                diagnostic_ref: null,
                evidence: {},
                reason: null,
                severity: 'warning',
                subcode: null,
                title: 'title',
            },
        ],
        checks: [
            {
                key: 'no_metric',
                name: 'No metric',
                description: 'description',
                reason: null,
                status: 'finding',
                values: {},
                rule: null,
            },
        ],
    }

    const buildContext = (getHealth: Mock): Context =>
        ({
            api: {
                getProjectBaseUrl: () => 'https://us.posthog.com/project/42',
                experiments: () => ({
                    getMetricResults: vi.fn().mockResolvedValue({
                        success: true,
                        data: {
                            experiment: { id: 7, name: 'Test', feature_flag_key: 'k', start_date: '2026-01-01' },
                            primaryMetricEntries: [],
                            secondaryMetricEntries: [],
                            primaryMetricsResults: [],
                            secondaryMetricsResults: [],
                            exposures,
                        },
                    }),
                    getHealth,
                }),
            },
            stateManager: {
                getProjectId: vi.fn().mockResolvedValue('42'),
                getAnalyticsContext: vi.fn().mockResolvedValue(undefined),
            },
            getDistinctId: vi.fn().mockResolvedValue('user-1'),
        }) as unknown as Context

    it.each([
        {
            name: 'adds the configuration checks when the flag is on',
            flag: (): Promise<boolean> => Promise.resolve(true),
            healthRead: { success: true, data: configHealth },
            readsHealth: true,
            checkKeys: ['no_metric', 'srm'],
        },
        {
            name: 'keeps the exposure checks only when the flag is off',
            flag: (): Promise<boolean> => Promise.resolve(false),
            healthRead: undefined,
            readsHealth: false,
            checkKeys: ['srm'],
        },
        {
            name: 'keeps the exposure checks only when the health read fails',
            flag: (): Promise<boolean> => Promise.resolve(true),
            healthRead: { success: false, error: new Error('Internal server error') },
            readsHealth: true,
            checkKeys: ['srm'],
        },
        {
            name: 'keeps the exposure checks only when the flag check throws',
            flag: (): Promise<boolean> => Promise.reject(new Error('flags unavailable')),
            healthRead: undefined,
            readsHealth: false,
            checkKeys: ['srm'],
        },
    ])('$name', async ({ flag, healthRead, readsHealth, checkKeys }) => {
        vi.mocked(isFeatureFlagEnabled).mockImplementation(flag)
        const getHealth = vi.fn().mockResolvedValue(healthRead)

        const result = await getResultsHandler(buildContext(getHealth), { id: 7, refresh: false })

        expect(isFeatureFlagEnabled).toHaveBeenCalledWith('experiment-health-findings', 'user-1', undefined)
        expect(getHealth).toHaveBeenCalledTimes(readsHealth ? 1 : 0)
        expect(result.health.checks.map((check) => check.key)).toEqual(checkKeys)
    })
})
