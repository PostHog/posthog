import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { ExperimentNotStartedError } from '@/lib/errors'
import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import { getHealthHandler } from '@/tools/experiments/getHealth'
import { getResultsHandler } from '@/tools/experiments/getResults'
import { readConfigHealth } from '@/tools/experiments/health'
import type { Context } from '@/tools/types'

vi.mock('@/lib/posthog/flags', () => ({ isFeatureFlagEnabled: vi.fn() }))

// The configuration checks reach agents only where the flag shows the health panel in the app. Without the
// gate, a customer's agent reports findings the customer cannot see; a failed read must not fail the tool.
describe('experiment health gate', () => {
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
        setup: null,
    }

    const buildContext = (getHealth: Mock, exposureRead: unknown, trackEvent: Mock): Context =>
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
                    getExposures: vi.fn().mockResolvedValue(exposureRead),
                    getHealth,
                }),
            },
            stateManager: {
                getProjectId: vi.fn().mockResolvedValue('42'),
                getAnalyticsContext: vi.fn().mockResolvedValue(undefined),
            },
            getDistinctId: vi.fn().mockResolvedValue('user-1'),
            trackEvent,
        }) as unknown as Context

    const readHealth = {
        'experiment-results-get': async (context: Context) => {
            const result = await getResultsHandler(context, { id: 7, refresh: false })
            return { summary: result.health.summary, codes: result.health.findings.map((f) => f.code) }
        },
        'experiment-health-get': async (context: Context) => {
            const result = await getHealthHandler(context, { id: 7 })
            return { summary: result.summary, codes: result.findings.map((f) => f.code) }
        },
    }

    const exposureOk = { success: true, data: { exposures } }

    it.each(
        (['experiment-results-get', 'experiment-health-get'] as const).flatMap((tool) => [
            {
                tool,
                name: 'adds the configuration checks when the flag is on',
                flag: (): Promise<boolean> => Promise.resolve(true),
                healthRead: { success: true, data: configHealth },
                readsHealth: true,
                codes: ['no_metric'],
                summary: 'Findings: 1 warning. Checks: 1 passed, 1 finding.',
                outcome: 'read',
            },
            {
                tool,
                name: 'keeps the exposure checks only when the flag is off',
                flag: (): Promise<boolean> => Promise.resolve(false),
                healthRead: undefined,
                readsHealth: false,
                codes: [],
                summary: 'Findings: none. Checks: 1 passed.',
                outcome: 'flag_off',
            },
            {
                tool,
                name: 'says the configuration checks did not run when the health read fails',
                flag: (): Promise<boolean> => Promise.resolve(true),
                healthRead: { success: false, error: new Error('Internal server error') },
                readsHealth: true,
                codes: [],
                summary: 'Findings: none. Checks: 1 passed. The configuration checks did not run.',
                outcome: 'failed',
            },
            {
                tool,
                name: 'keeps the exposure checks only when the flag check throws',
                flag: (): Promise<boolean> => Promise.reject(new Error('flags unavailable')),
                healthRead: undefined,
                readsHealth: false,
                codes: [],
                summary: 'Findings: none. Checks: 1 passed.',
                outcome: 'flag_off',
            },
        ])
    )('$tool $name', async ({ tool, flag, healthRead, readsHealth, codes, summary, outcome }) => {
        vi.mocked(isFeatureFlagEnabled).mockImplementation(flag)
        const getHealth = vi.fn().mockResolvedValue(healthRead)
        const trackEvent = vi.fn().mockResolvedValue(undefined)

        const result = await readHealth[tool](buildContext(getHealth, exposureOk, trackEvent))

        expect(isFeatureFlagEnabled).toHaveBeenCalledWith('experiment-health-findings', 'user-1', undefined)
        expect(getHealth).toHaveBeenCalledTimes(readsHealth ? 1 : 0)
        expect(result).toEqual({ summary, codes })
        expect(trackEvent).toHaveBeenCalledWith(
            'mcp experiment health returned',
            expect.objectContaining({
                tool_name: tool,
                experiment_id: 7,
                health_finding_codes: codes,
                configuration_checks_outcome: outcome,
                exposure_checks_outcome: 'read',
            })
        )
    })

    const draftExposureRead = {
        success: false,
        error: new ExperimentNotStartedError('Experiment "Test" has not started yet.'),
    }

    it.each([
        {
            name: 'returns the configuration checks of a draft',
            flag: true,
            codes: ['no_metric'],
            summary:
                'Findings: 1 warning. Checks: 1 finding. The exposure checks did not run: the experiment has not started.',
        },
        {
            name: 'answers for a draft without the flag',
            flag: false,
            codes: [],
            summary:
                'Findings: none. Checks: none ran. The exposure checks did not run: the experiment has not started.',
        },
    ])('experiment-health-get $name', async ({ flag, codes, summary }) => {
        vi.mocked(isFeatureFlagEnabled).mockResolvedValue(flag)
        const getHealth = vi.fn().mockResolvedValue({ success: true, data: configHealth })

        const result = await getHealthHandler(buildContext(getHealth, draftExposureRead, vi.fn()), { id: 7 })

        expect(result.findings.map((f) => f.code)).toEqual(codes)
        expect(result.summary).toBe(summary)
        expect(result).not.toHaveProperty('exposures')
    })

    it('experiment-health-get fails when the exposure query fails and the flag is off', async () => {
        vi.mocked(isFeatureFlagEnabled).mockResolvedValue(false)
        const failedRead = { success: false, error: new Error('Internal server error') }

        await expect(getHealthHandler(buildContext(vi.fn(), failedRead, vi.fn()), { id: 7 })).rejects.toThrow(
            'Failed to get experiment health'
        )
    })

    it('counts a flag check that outlasts the deadline as off', async () => {
        vi.mocked(isFeatureFlagEnabled).mockReturnValue(new Promise(() => {}))
        const getHealth = vi.fn()

        const read = await readConfigHealth(buildContext(getHealth, exposureOk, vi.fn()), '42', 7, 10)

        expect(read).toEqual({ health: null, outcome: 'flag_off' })
        expect(getHealth).not.toHaveBeenCalled()
    })

    it('experiment-health-get returns the exposure counts without their health fields', async () => {
        vi.mocked(isFeatureFlagEnabled).mockResolvedValue(false)

        const result = await getHealthHandler(buildContext(vi.fn(), exposureOk, vi.fn()), { id: 7 })

        expect(result.exposures).toEqual({
            kind: 'ExperimentExposureQuery',
            timeseries: [],
            total_exposures: {},
            date_range: { date_from: '2026-01-01T00:00:00Z', date_to: null },
        })
    })
})
