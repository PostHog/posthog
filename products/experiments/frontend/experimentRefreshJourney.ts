import type { CustomerJourney, CustomerJourneySummary } from 'lib/customerJourneys/createCustomerJourney'
import { customerJourneyFailure } from 'lib/customerJourneys/customerJourneyFailure'
import { CustomerJourneyScope } from 'lib/customerJourneys/CustomerJourneyScope'
import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'

import type { ExperimentMetricsRecalculationApi } from './generated/api.schemas'

export type ExperimentRefreshMode = 'recalculation' | 'per_metric'
export type ExperimentMetricGroups = Record<'primary' | 'secondary', string[]>
export interface ExperimentRefreshReady {
    attemptId: string
    mode: ExperimentRefreshMode
    primary: unknown[]
    secondary: unknown[]
    exposures: unknown
}
export interface ExperimentRefreshObservation {
    attemptId: string
    bindRun: (runId: string) => void
    results: (
        run: Pick<ExperimentMetricsRecalculationApi, 'id' | 'status' | 'failed_metrics' | 'metric_errors' | 'results'>
    ) => void
    fail: (outcome: 'failed' | 'timed_out', error: 'query_error' | 'load_error' | 'timeout') => void
}
interface Attempt {
    id: string
    handle: CustomerJourney
    groups: ExperimentMetricGroups
    mode: ExperimentRefreshMode
    runId?: string
    primary?: unknown[]
    secondary?: unknown[]
    exposures?: unknown
    exposuresCached?: boolean
    ready?: ExperimentRefreshReady
}

export function isExperimentRefreshCommitted(
    ready: ExperimentRefreshReady,
    primary: readonly unknown[],
    secondary: readonly unknown[],
    exposures: unknown
): boolean {
    return (
        ready.exposures === exposures &&
        (['primary', 'secondary'] as const).every((group) => {
            const actual = group === 'primary' ? primary : secondary
            return (
                ready[group].length === actual.length && ready[group].every((result, index) => result === actual[index])
            )
        })
    )
}

export class ExperimentRefreshJourneyController {
    private observed = false
    private readonly scope = new CustomerJourneyScope<Attempt>(
        (attempt) => this.summary(attempt),
        () => this.onReady(null)
    )
    public constructor(private readonly onReady: (ready: ExperimentRefreshReady | null) => void) {}

    public observe(observed: boolean): void {
        this.observed = observed
        if (!observed) {
            this.dispose('observation_stopped')
        }
    }

    public start(
        experimentId: number,
        refreshId: string,
        groups: ExperimentMetricGroups,
        mode: ExperimentRefreshMode
    ): ExperimentRefreshObservation | null {
        const attempt = this.scope.replace(() => {
            if (!this.observed || [...groups.primary, ...groups.secondary].some((uuid) => !uuid)) {
                return null
            }
            const handle = startCustomerJourney({
                journey_name: 'experiment_refresh',
                resource_type: 'experiment',
                resource_id: experimentId,
                attempt_id: refreshId,
                execution_path: mode,
                trigger: 'manual_refresh',
                readiness_contract_version: 1,
                readiness_scope: 'modern_experiment_results',
            })
            return handle
                ? {
                      id: refreshId,
                      handle,
                      groups: { primary: [...groups.primary], secondary: [...groups.secondary] },
                      mode,
                      primary: groups.primary.length === 0 ? [] : undefined,
                      secondary: groups.secondary.length === 0 ? [] : undefined,
                  }
                : null
        })
        if (!attempt) {
            return null
        }
        return {
            attemptId: refreshId,
            bindRun: (id) => {
                if (this.scope.current === attempt) {
                    attempt.runId = id
                }
            },
            results: (run) => {
                if (
                    this.scope.current !== attempt ||
                    attempt.runId !== run.id ||
                    !['completed', 'failed'].includes(run.status)
                ) {
                    return
                }
                const results = new Map((run.results ?? []).map((entry) => [entry.metric_uuid, entry]))
                const errors = run.metric_errors && typeof run.metric_errors === 'object' ? run.metric_errors : {}
                if (
                    run.status === 'failed' ||
                    run.failed_metrics > 0 ||
                    [...attempt.groups.primary, ...attempt.groups.secondary].some((uuid) => {
                        const entry = results.get(uuid)
                        return uuid in errors || !entry || entry.status === 'failed' || entry.result == null
                    })
                ) {
                    this.fail(refreshId, 'failed', 'query_error')
                    return
                }
                attempt.primary = attempt.groups.primary.map((uuid) => results.get(uuid)!.result)
                attempt.secondary = attempt.groups.secondary.map((uuid) => results.get(uuid)!.result)
                this.publish(attempt)
            },
            fail: (outcome, error) => this.fail(refreshId, outcome, error),
        }
    }

    public group(id: string, group: 'primary' | 'secondary', results: unknown[], errors: unknown[]): void {
        const attempt = this.scope.current
        if (!attempt || attempt.id !== id) {
            return
        }
        if (errors.some(Boolean) || attempt.groups[group].some((_, index) => results[index] == null)) {
            const error = errors.find(Boolean) as { statusCode?: number; code?: string } | undefined
            const { outcome, error_type } = customerJourneyFailure({ status: error?.statusCode, code: error?.code })
            this.fail(id, outcome, error_type)
            return
        }
        attempt[group] = [...results]
        this.publish(attempt)
    }

    public exposures(id: string, response: unknown): void {
        const attempt = this.scope.current
        if (!attempt || attempt.id !== id) {
            return
        }
        if (
            !response ||
            typeof response !== 'object' ||
            !('timeseries' in response) ||
            !Array.isArray(response.timeseries)
        ) {
            this.fail(id, 'failed', 'load_error')
            return
        }
        attempt.exposures = response
        if ('is_cached' in response && typeof response.is_cached === 'boolean') {
            attempt.exposuresCached = response.is_cached
        }
        this.publish(attempt)
    }

    public fail(
        id: string,
        outcome: 'failed' | 'timed_out',
        error: NonNullable<CustomerJourneySummary['error_type']>
    ): void {
        if (this.scope.current?.id === id) {
            this.scope.finish(outcome, { error_type: error })
        }
    }

    public committed(id: string): void {
        const attempt = this.scope.current
        if (this.observed && attempt?.id === id && attempt.ready) {
            this.scope.firstUseful()
            this.scope.finish('usable', this.summary(attempt, true))
        }
    }

    public dispose(reason: 'superseded' | 'observation_stopped'): void {
        this.scope.dispose(reason)
    }

    private publish(attempt: Attempt): void {
        if (attempt.primary && attempt.secondary && attempt.exposures !== undefined) {
            attempt.ready = {
                attemptId: attempt.id,
                mode: attempt.mode,
                primary: attempt.primary,
                secondary: attempt.secondary,
                exposures: attempt.exposures,
            }
            this.onReady(attempt.ready)
        }
    }

    private summary(attempt: Attempt, committed = false): CustomerJourneySummary {
        const total = attempt.groups.primary.length + attempt.groups.secondary.length + 1
        return {
            total_count: total,
            ...(attempt.runId ? { experiment_run_id: attempt.runId } : {}),
            // Partial responses are not evidence of committed usable results.
            ...(committed ? { ready_count: total, failed_count: 0, pending_count: 0 } : {}),
            ...(attempt.exposuresCached !== undefined ? { exposures_response_cached: attempt.exposuresCached } : {}),
        }
    }
}
