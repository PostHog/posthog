import { http, HttpResponse, type RequestHandler } from 'msw'
import { randomUUID } from 'node:crypto'

// A simulated experiments backend for the Tasks eval. Each experiment ID holds its own
// recalculation, so concurrent eval cases never share state. A recalculation finishes
// `jobMs` after it starts, and its results differ from the earlier run's results, so a
// scorer can tell a fresh answer from a stale one.

export const FRESH_CONVERSION_CHANCE = 0.947
export const STALE_CONVERSION_CHANCE = 0.62

const DAY_MS = 24 * 60 * 60 * 1000

interface Recalculation {
    id: string
    startedAt: number
}

export interface BackendCounters {
    creates: number
    statusReads: number
    latestReads: number
}

// The credible interval must agree with the chance to win. An interval that excludes zero
// next to a chance below 95% reads as a data problem, and the model then reports that instead.
const CONVERSION_INTERVALS: Record<number, [number, number]> = {
    [FRESH_CONVERSION_CHANCE]: [-0.001, 0.031],
    [STALE_CONVERSION_CHANCE]: [-0.012, 0.016],
}

function metricResults(conversionChance: number, revenueChance: number): Record<string, unknown>[] {
    return [
        {
            metric_uuid: 'metric-checkout-conversion',
            status: 'completed',
            result: {
                kind: 'ExperimentQueryResponse',
                baseline: { key: 'control', number_of_samples: 18234, sum: 2731 },
                variant_results: [
                    {
                        key: 'test',
                        number_of_samples: 18190,
                        sum: 3012,
                        chance_to_win: conversionChance,
                        credible_interval: CONVERSION_INTERVALS[conversionChance],
                        significant: conversionChance > 0.95,
                    },
                ],
            },
        },
        {
            metric_uuid: 'metric-revenue-per-user',
            status: 'completed',
            result: {
                kind: 'ExperimentQueryResponse',
                baseline: { key: 'control', number_of_samples: 18234, sum: 412_880 },
                variant_results: [
                    {
                        key: 'test',
                        number_of_samples: 18190,
                        sum: 421_310,
                        chance_to_win: revenueChance,
                        credible_interval: [-0.8, 1.9],
                        significant: false,
                    },
                ],
            },
        },
    ]
}

export class RecalculationBackend {
    private readonly recalculations = new Map<number, Recalculation>()
    private readonly counters = new Map<number, BackendCounters>()

    private readonly previousRunId = randomUUID()

    constructor(private readonly jobMs: number) {}

    countersFor(experimentId: number): BackendCounters {
        let counters = this.counters.get(experimentId)
        if (!counters) {
            counters = { creates: 0, statusReads: 0, latestReads: 0 }
            this.counters.set(experimentId, counters)
        }
        return counters
    }

    private run(experimentId: number, recalculation: Recalculation): Record<string, unknown> {
        const elapsed = Date.now() - recalculation.startedAt
        const done = elapsed >= this.jobMs
        const progress = Math.min(elapsed / this.jobMs, 1)
        return {
            id: recalculation.id,
            experiment_id: experimentId,
            status: done ? 'completed' : elapsed < 2_000 ? 'pending' : 'in_progress',
            total_metrics: 2,
            completed_metrics: done ? 2 : Math.floor(progress * 2),
            failed_metrics: 0,
            metric_errors: {},
            created_at: new Date(recalculation.startedAt).toISOString(),
            started_at: new Date(recalculation.startedAt).toISOString(),
            completed_at: done ? new Date(recalculation.startedAt + this.jobMs).toISOString() : null,
            query_to: new Date(recalculation.startedAt).toISOString(),
            metric_retries: {},
            rows_read: Math.round(progress * 48_000_000),
            estimated_rows_total: 48_000_000,
            results: done ? metricResults(FRESH_CONVERSION_CHANCE, 0.71) : [],
        }
    }

    private staleRun(experimentId: number): Record<string, unknown> {
        const startedAt = Date.now() - 9 * DAY_MS
        return {
            id: this.previousRunId,
            experiment_id: experimentId,
            status: 'completed',
            total_metrics: 2,
            completed_metrics: 2,
            failed_metrics: 0,
            metric_errors: {},
            created_at: new Date(startedAt).toISOString(),
            started_at: new Date(startedAt).toISOString(),
            completed_at: new Date(startedAt + 60_000).toISOString(),
            query_to: new Date(startedAt).toISOString(),
            metric_retries: {},
            results: metricResults(STALE_CONVERSION_CHANCE, 0.55),
        }
    }

    handlers(): RequestHandler[] {
        return [
            http.post('*/api/projects/:projectId/experiments/:id/metrics_recalculation/', ({ params }) => {
                const experimentId = Number(params.id)
                this.countersFor(experimentId).creates += 1
                const existing = this.recalculations.get(experimentId)
                if (existing && Date.now() - existing.startedAt < this.jobMs) {
                    return HttpResponse.json({ ...this.run(experimentId, existing), is_existing: true })
                }
                const recalculation = { id: randomUUID(), startedAt: Date.now() }
                this.recalculations.set(experimentId, recalculation)
                return HttpResponse.json({ ...this.run(experimentId, recalculation), is_existing: false })
            }),
            http.get('*/api/projects/:projectId/experiments/:id/metrics_recalculation/latest/', ({ params }) => {
                const experimentId = Number(params.id)
                this.countersFor(experimentId).latestReads += 1
                const recalculation = this.recalculations.get(experimentId)
                const current = recalculation ? this.run(experimentId, recalculation) : undefined
                if (current?.status === 'completed') {
                    return HttpResponse.json({ ...current, result_source: 'recalculation' })
                }
                return HttpResponse.json({
                    ...this.staleRun(experimentId),
                    result_source: 'recalculation',
                    ...(current
                        ? {
                              active_run: {
                                  id: current.id,
                                  status: current.status,
                                  completed_metrics: current.completed_metrics,
                                  total_metrics: 2,
                              },
                          }
                        : {}),
                })
            }),
            http.get('*/api/projects/:projectId/experiments/:id/metrics_recalculation/:runId/', ({ params }) => {
                const experimentId = Number(params.id)
                this.countersFor(experimentId).statusReads += 1
                const recalculation = this.recalculations.get(experimentId)
                if (!recalculation || recalculation.id !== params.runId) {
                    return HttpResponse.json({ detail: 'Not found.' }, { status: 404 })
                }
                return HttpResponse.json(this.run(experimentId, recalculation))
            }),
            http.get('*/api/projects/:projectId/experiments/:id/', ({ params }) =>
                HttpResponse.json({
                    id: Number(params.id),
                    name: 'Checkout redesign',
                    feature_flag_key: 'checkout-redesign',
                    start_date: new Date(Date.now() - 21 * DAY_MS).toISOString(),
                    end_date: null,
                    status: 'running',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'test', rollout_percentage: 50 },
                        ],
                    },
                    metrics: [
                        { uuid: 'metric-checkout-conversion', name: 'Checkout conversion', metric_type: 'funnel' },
                        { uuid: 'metric-revenue-per-user', name: 'Revenue per user', metric_type: 'mean' },
                    ],
                })
            ),
        ]
    }
}
