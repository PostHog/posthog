import { ExperimentConclusion, ExperimentStatsMethod, ExperimentStatus } from '~/types'

import {
    ExperimentMetaBarInput,
    getExperimentMetaBarVisibility,
    getExperimentStatsSummary,
} from './experimentMetaBarUtils'

describe('experimentMetaBarUtils', () => {
    describe('getExperimentMetaBarVisibility', () => {
        it.each<[string, ExperimentMetaBarInput, ReturnType<typeof getExperimentMetaBarVisibility>]>([
            [
                'draft',
                { status: ExperimentStatus.Draft, start_date: null, end_date: null, conclusion: null },
                { showDateRange: false, showRemainingTime: true, showRefresh: false, showConclusion: false },
            ],
            [
                'running',
                {
                    status: ExperimentStatus.Running,
                    start_date: '2026-08-10T07:10:00Z',
                    end_date: null,
                    conclusion: null,
                },
                { showDateRange: true, showRemainingTime: true, showRefresh: true, showConclusion: false },
            ],
            [
                'paused',
                {
                    status: ExperimentStatus.Paused,
                    start_date: '2026-08-10T07:10:00Z',
                    end_date: null,
                    conclusion: null,
                },
                { showDateRange: true, showRemainingTime: true, showRefresh: true, showConclusion: false },
            ],
            [
                'stopped with a conclusion',
                {
                    status: ExperimentStatus.Stopped,
                    start_date: '2026-07-17T04:15:00Z',
                    end_date: '2026-08-10T07:10:00Z',
                    conclusion: ExperimentConclusion.StoppedEarly,
                },
                { showDateRange: true, showRemainingTime: false, showRefresh: false, showConclusion: true },
            ],
            [
                'stopped without a conclusion',
                {
                    status: ExperimentStatus.Stopped,
                    start_date: '2026-07-17T04:15:00Z',
                    end_date: '2026-08-10T07:10:00Z',
                    conclusion: null,
                },
                { showDateRange: true, showRemainingTime: false, showRefresh: false, showConclusion: false },
            ],
        ])('%s', (_, experiment, expected) => {
            expect(getExperimentMetaBarVisibility(experiment)).toEqual(expected)
        })
    })

    describe('getExperimentStatsSummary', () => {
        it.each([
            [ExperimentStatsMethod.Bayesian, { bayesian: { ci_level: 0.9 } }, 'Bayesian', '90%'],
            [ExperimentStatsMethod.Frequentist, { frequentist: { alpha: 0.01 } }, 'Frequentist', '99%'],
            [ExperimentStatsMethod.Bayesian, undefined, 'Bayesian', '95%'],
        ])('%s with %j', (statsMethod, stats_config, method, level) => {
            expect(getExperimentStatsSummary({ stats_config: stats_config as any }, statsMethod)).toMatchObject({
                method,
                level,
            })
        })
    })
})
