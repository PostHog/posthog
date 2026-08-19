import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { FeatureFlagEvaluationRuntime, FeatureFlagGroupType } from '~/types'

import { FractionalRolloutWarning, fractionalRolloutPercentages } from './FractionalRolloutWarning'

function group(rollout_percentage: number | null): FeatureFlagGroupType {
    return { properties: [], rollout_percentage, variant: null, sort_key: `group-${rollout_percentage}` }
}

function renderWarning(
    filterGroups: FeatureFlagGroupType[],
    evaluationRuntime?: FeatureFlagEvaluationRuntime
): HTMLElement {
    const { container } = render(
        <Provider>
            <FractionalRolloutWarning filterGroups={filterGroups} evaluationRuntime={evaluationRuntime} />
        </Provider>
    )
    return container
}

describe('fractionalRolloutPercentages', () => {
    it('picks out only percentages that are not whole numbers', () => {
        expect(fractionalRolloutPercentages([group(100), group(0.5), group(0), group(33.33)])).toEqual([0.5, 33.33])
    })

    it('ignores null and missing rollout percentages', () => {
        expect(fractionalRolloutPercentages([group(null), {}])).toEqual([])
        expect(fractionalRolloutPercentages(undefined)).toEqual([])
    })
})

describe('FractionalRolloutWarning', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('warns and names the offending percentage', () => {
        renderWarning([group(100), group(0.5)])

        expect(document.body).toHaveTextContent('fractional rollout percentage (0.5%)')
        expect(document.body).toHaveTextContent('every flag in the project')
    })

    it('lists every offending percentage when several condition sets are fractional', () => {
        renderWarning([group(0.5), group(33.33)])

        expect(document.body).toHaveTextContent('(0.5%, 33.33%)')
    })

    it('stays silent when every rollout percentage is a whole number', () => {
        expect(renderWarning([group(100), group(0), group(50)])).toBeEmptyDOMElement()
    })

    // Local evaluation is server-side only, so a client-only flag never parses the definitions payload.
    it('stays silent for client-only flags', () => {
        expect(renderWarning([group(0.5)], FeatureFlagEvaluationRuntime.CLIENT)).toBeEmptyDOMElement()
    })

    it.each([FeatureFlagEvaluationRuntime.SERVER, FeatureFlagEvaluationRuntime.ALL])(
        'warns for the %s evaluation runtime',
        (evaluationRuntime) => {
            renderWarning([group(0.5)], evaluationRuntime)

            expect(document.body).toHaveTextContent('fractional rollout percentage')
        }
    )
})
