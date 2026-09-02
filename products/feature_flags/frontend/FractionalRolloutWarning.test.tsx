import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { FeatureFlagGroupType } from '~/types'

import { FractionalRolloutWarning, fractionalRolloutPercentages } from './FractionalRolloutWarning'

function group(rollout_percentage: number | null, variant: string | null = null): FeatureFlagGroupType {
    return { properties: [], rollout_percentage, variant, sort_key: `group-${rollout_percentage}-${variant}` }
}

// A condition group can carry a variant override. The group's own rollout is what breaks the parse,
// so the override must not change whether the warning fires.
const variantOverrideCases: [number, boolean][] = [
    [0.5, true],
    [50, false],
]

// Flags saved through the API carry more precision than the editor's two decimal places allows.
const precisionCases: [number, string][] = [
    [33.333333333333336, '(33.33%)'],
    [0.00015, '(0.00015%)'],
]

function renderWarning(filterGroups: FeatureFlagGroupType[]): HTMLElement {
    const { container } = render(
        <Provider>
            <FractionalRolloutWarning filterGroups={filterGroups} />
        </Provider>
    )
    return container
}

describe('FractionalRolloutWarning', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    describe('fractionalRolloutPercentages', () => {
        it('picks out only percentages that are not whole numbers', () => {
            expect(fractionalRolloutPercentages([group(100), group(0.5), group(0), group(33.33)])).toEqual([0.5, 33.33])
        })

        it('ignores null and missing rollout percentages', () => {
            expect(fractionalRolloutPercentages([group(null), {}])).toEqual([])
            expect(fractionalRolloutPercentages(undefined)).toEqual([])
        })
    })

    describe('rendering', () => {
        it('warns and names the offending percentage', () => {
            renderWarning([group(100), group(0.5)])

            expect(document.body).toHaveTextContent('This flag has a fractional rollout percentage (0.5%)')
            expect(document.body).toHaveTextContent('every flag in the project')
        })

        it('pluralizes and lists every percentage when several condition sets are fractional', () => {
            renderWarning([group(0.5), group(33.33)])

            expect(document.body).toHaveTextContent('This flag has fractional rollout percentages (0.5%, 33.33%)')
        })

        it('stays silent when every rollout percentage is a whole number', () => {
            expect(renderWarning([group(100), group(0), group(50)])).toBeEmptyDOMElement()
        })

        it.each(variantOverrideCases)('with rollout %s on a group targeting a variant, warns: %s', (rollout, warns) => {
            const container = renderWarning([group(rollout, 'test')])

            if (warns) {
                expect(container).toHaveTextContent('fractional rollout percentage')
            } else {
                expect(container).toBeEmptyDOMElement()
            }
        })

        it.each(precisionCases)('trims %s for display without rounding it to zero', (rollout, expected) => {
            expect(renderWarning([group(rollout)])).toHaveTextContent(expected)
        })
    })
})
