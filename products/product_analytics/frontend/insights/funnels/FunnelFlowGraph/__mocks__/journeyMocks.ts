import { FEATURE_FLAGS } from 'lib/constants'

import { makeStep } from './nodeStoryUtils'

const STEP_NAMES = ['Sign up', 'Complete profile', 'First action', 'Activation']

export function makeFunnelStep(name: string, order: number, count: number): Record<string, unknown> {
    return makeStep(name, order, count, count) as unknown as Record<string, unknown>
}

export function makeInsight(optionalStepIndices: number[] = []): Record<string, unknown> {
    const series = STEP_NAMES.map((name, i) => ({
        kind: 'EventsNode',
        event: name,
        ...(optionalStepIndices.includes(i) ? { optionalInFunnel: true } : {}),
    }))
    return {
        id: 1,
        short_id: 'insight-1',
        name: 'Onboarding Funnel',
        derived_name: 'Onboarding Funnel',
        description: '',
        deleted: false,
        saved: true,
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series,
                funnelsFilter: { funnelVizType: 'flow' },
            },
        },
        result: null,
        created_at: '2024-01-01T00:00:00Z',
        last_modified_at: '2024-01-01T00:00:00Z',
        filters: {},
        order: null,
        color: null,
        layouts: {},
        tags: [],
        dashboards: [],
    }
}

export const journeysList = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'journey-1',
            insight: 1,
            name: 'Onboarding Journey',
            description: '',
        },
    ],
}

export const emptyJourneysList = {
    count: 0,
    next: null,
    previous: null,
    results: [] as unknown[],
}

export const JOURNEY_FEATURE_FLAGS = [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]

export function allCompletedSteps(): Record<string, unknown>[] {
    return [
        makeFunnelStep('Sign up', 0, 100),
        makeFunnelStep('Complete profile', 1, 85),
        makeFunnelStep('First action', 2, 70),
        makeFunnelStep('Activation', 3, 55),
    ]
}

export function someCompletedSteps(): Record<string, unknown>[] {
    return [
        makeFunnelStep('Sign up', 0, 1),
        makeFunnelStep('Complete profile', 1, 1),
        makeFunnelStep('First action', 2, 0),
        makeFunnelStep('Activation', 3, 0),
    ]
}

export function noCompletedSteps(): Record<string, unknown>[] {
    return [
        makeFunnelStep('Sign up', 0, 0),
        makeFunnelStep('Complete profile', 1, 0),
        makeFunnelStep('First action', 2, 0),
        makeFunnelStep('Activation', 3, 0),
    ]
}

export function optionalStepResults(): Record<string, unknown>[] {
    return [
        makeFunnelStep('Sign up', 0, 1),
        makeFunnelStep('Complete profile', 1, 1),
        makeFunnelStep('First action', 2, 1),
        makeFunnelStep('Activation', 3, 0),
    ]
}
