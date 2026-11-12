import type { ExperimentApi, ExperimentFlagCleanupTargetApi } from '@/api/experiments'

import type { PrimaryResult, VariantResult } from './experimentModel'
import {
    type CleanupTargetState,
    type FinishContext,
    type FinishForm,
    finishContextOf,
    finishDisabledReason,
    finishRequestOf,
    initialFinishForm,
    rolledOutVariantOf,
    variantOptions,
} from './finishModel'

function experiment(filters: Record<string, unknown>, active = true): ExperimentApi {
    return {
        id: 7,
        name: 'Checkout CTA copy',
        feature_flag_key: 'checkout-cta',
        feature_flag: { id: 3, team_id: 1, key: 'checkout-cta', active, filters, evaluation_contexts: [] },
    } as unknown as ExperimentApi
}

const SPLIT = {
    groups: [{ properties: [], rollout_percentage: 100 }],
    multivariate: {
        variants: [
            { key: 'control', rollout_percentage: 34 },
            { key: 'start-trial', rollout_percentage: 33 },
            { key: 'get-started', rollout_percentage: 33 },
        ],
    },
}

function variant(key: string, overrides: Partial<VariantResult> = {}): VariantResult {
    return {
        key,
        samples: 1000,
        value: 0.1,
        delta: 0.05,
        interval: [0.01, 0.09],
        significant: false,
        better: true,
        ...overrides,
    }
}

function primary(variants: VariantResult[]): PrimaryResult {
    return {
        metric: { uuid: 'm1', name: 'Checkout completed', goal: 'increase', metricType: 'funnel' },
        baseline: { key: 'control', samples: 1000, value: 0.1 },
        variants,
    }
}

const READY_SINGLE: CleanupTargetState = {
    status: 'ready',
    target: { repository: 'example-org/web', source: 'single_repo', candidates: ['example-org/web'] },
}
const AMBIGUOUS: ExperimentFlagCleanupTargetApi = {
    repository: null,
    source: 'ambiguous',
    candidates: ['example-org/web', 'example-org/api'],
}

function form(overrides: Partial<FinishForm> = {}): FinishForm {
    return {
        preset: 'ship',
        variant: 'start-trial',
        release: 'population',
        conclusion: 'won',
        comment: '',
        cleanup: false,
        repository: null,
        ...overrides,
    }
}

const CONTEXT: FinishContext = finishContextOf(experiment(SPLIT), null)

describe('finishModel', () => {
    it.each([
        ['a running split', SPLIT, true, null],
        [
            'shipped to everyone',
            {
                ...SPLIT,
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 0 },
                        { key: 'b', rollout_percentage: 100 },
                    ],
                },
            },
            true,
            'b',
        ],
        [
            'shipped to the population only, so release conditions remain',
            {
                groups: [{ properties: [{ key: 'email' }], rollout_percentage: 100 }],
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 0 },
                        { key: 'b', rollout_percentage: 100 },
                    ],
                },
            },
            true,
            null,
        ],
        [
            'shipped but the flag is off',
            {
                ...SPLIT,
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 0 },
                        { key: 'b', rollout_percentage: 100 },
                    ],
                },
            },
            false,
            null,
        ],
    ])('finds the rolled out variant like the web: %s', (_name, filters, active, expected) => {
        expect(rolledOutVariantOf(experiment(filters, active))).toBe(expected)
    })

    it('starts Ship on the leader with Won and End with no variant and the suggested conclusion', () => {
        const results = primary([
            variant('start-trial', { chanceToWin: 0.99, significant: true }),
            variant('get-started', { chanceToWin: 0.7 }),
        ])
        const context = finishContextOf(experiment(SPLIT), results)
        expect(initialFinishForm('ship', context)).toMatchObject({
            variant: 'start-trial',
            conclusion: 'won',
            release: 'population',
        })
        expect(initialFinishForm('end', context)).toMatchObject({ variant: null, conclusion: 'won' })
        expect(initialFinishForm('end', finishContextOf(experiment(SPLIT), null))).toMatchObject({ conclusion: null })
    })

    it.each<[string, Partial<FinishForm>, CleanupTargetState, string | null]>([
        [
            'no conclusion wins over everything',
            { conclusion: null, cleanup: true },
            { status: 'loading' },
            'Select a conclusion',
        ],
        ['cleanup off ignores the target', { cleanup: false }, { status: 'loading' }, null],
        [
            'target still loading',
            { cleanup: true },
            { status: 'loading' },
            'Checking which repository the cleanup PR would target',
        ],
        [
            'ambiguous without a pick',
            { cleanup: true },
            { status: 'ready', target: AMBIGUOUS },
            'Select a repository for the cleanup PR',
        ],
        [
            'ambiguous with a pick',
            { cleanup: true, repository: 'example-org/api' },
            { status: 'ready', target: AMBIGUOUS },
            null,
        ],
        [
            'no GitHub leaves the PR out instead of blocking',
            { cleanup: true },
            { status: 'ready', target: { repository: null, source: 'no_integration', candidates: [] } },
            null,
        ],
        ['no task:write leaves the PR out', { cleanup: true }, { status: 'unavailable' }, null],
    ])('disables the button with the web reason: %s', (_name, overrides, cleanup, reason) => {
        expect(finishDisabledReason(form(overrides), cleanup)).toBe(reason)
    })

    it('ships with the release mode and sends a repository only for an ambiguous target', () => {
        const request = finishRequestOf(
            form({ release: 'everyone', cleanup: true, repository: 'example-org/api', comment: '  clear win ' }),
            CONTEXT,
            { status: 'ready', target: AMBIGUOUS }
        )
        expect(request).toEqual({
            kind: 'ship',
            variant: 'start-trial',
            body: {
                variant_key: 'start-trial',
                release_to_everyone: true,
                conclusion: 'won',
                conclusion_comment: 'clear win',
                open_cleanup_pr: true,
                repository: 'example-org/api',
            },
        })
        const known = finishRequestOf(form({ cleanup: true, repository: 'example-org/api' }), CONTEXT, READY_SINGLE)
        expect(known.body).not.toHaveProperty('repository')
        expect(known.body).not.toHaveProperty('set_repository_as_team_default')
    })

    it.each<[string, Partial<FinishForm>, FinishContext, CleanupTargetState]>([
        ['no variant picked', { variant: null, conclusion: 'lost' }, CONTEXT, READY_SINGLE],
        [
            'a variant is already at 100%',
            { conclusion: 'lost' },
            { ...CONTEXT, rolledOut: 'start-trial' },
            READY_SINGLE,
        ],
    ])('ends without shipping when %s', (_name, overrides, context, cleanup) => {
        expect(finishRequestOf(form(overrides), context, cleanup)).toEqual({
            kind: 'end',
            body: { conclusion: 'lost', conclusion_comment: null, open_cleanup_pr: false },
        })
    })

    it('never asks for a cleanup PR without GitHub, even when the box was ticked first', () => {
        const request = finishRequestOf(form({ cleanup: true }), CONTEXT, {
            status: 'ready',
            target: { repository: null, source: 'no_integration', candidates: [] },
        })
        expect(request.body.open_cleanup_pr).toBe(false)
    })

    it.each([
        [
            'Bayesian by chance to win',
            'bayes',
            [
                variant('get-started', { chanceToWin: 0.7 }),
                variant('start-trial', { chanceToWin: 0.99, significant: true }),
            ],
            ['start-trial', 'get-started', 'control', null],
        ],
        [
            'Frequentist by p-value among better variants',
            'freq',
            [variant('start-trial', { pValue: 0.2 }), variant('get-started', { pValue: 0.01 })],
            ['get-started', 'start-trial', 'control', null],
        ],
        [
            'Frequentist better before a significantly worse variant',
            'freq',
            [
                variant('start-trial', { pValue: 0.001, delta: -0.1, better: false, significant: true }),
                variant('get-started', { pValue: 0.3, better: true }),
            ],
            ['get-started', 'start-trial', 'control', null],
        ],
        ['without results in flag order', 'freq', [], ['start-trial', 'get-started', 'control', null]],
    ] as const)('orders the variants to ship: %s, control and None last', (_name, method, variants, keys) => {
        const results = variants.length ? primary([...variants]) : null
        const context = finishContextOf(experiment(SPLIT), results)
        expect(variantOptions(context, results, method).map((option) => option.key)).toEqual(keys)
    })
})
