import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { FeatureFlagRulesV2Config } from '~/types'

import { FeatureFlagRulesV2Readonly } from './FeatureFlagRulesV2Readonly'

const CONFIG: FeatureFlagRulesV2Config = {
    version: 2,
    return_type: 'boolean',
    default_value: false,
    rules: [
        {
            id: 'rule-1',
            rule_type: 'percentage_rollout',
            description: 'Half of everyone',
            targeting: { properties: [] },
            value: true,
            rollout_percentage: 50,
            on_rollout_miss: 'return_default',
            assignment_algorithm: 'sha1_v1',
            seed: 'seed-must-not-render',
        },
    ],
}

describe('FeatureFlagRulesV2Readonly', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the rule but never its seed', () => {
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={CONFIG} />
            </Provider>
        )

        expect(container).toHaveTextContent('Half of everyone')
        expect(container).toHaveTextContent('50%')
        expect(container).not.toHaveTextContent('seed-must-not-render')
    })

    it('shows a variant split with its variants, pause and holdout, but never a seed', () => {
        const split = {
            rule_type: 'experiment' as const,
            targeting: { properties: [] },
            paused: true,
            rollout_percentage: 50,
            on_rollout_miss: 'continue' as const,
            assignment_algorithm: 'sha1_60_v1',
            seed: 'rule-seed-must-not-render',
            variants: [
                { key: 'control', weight: 33.34, value: 'standard' },
                { key: 'compact', weight: 66.66, value: 'compact-layout' },
            ],
        }
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly
                    config={{
                        version: 2,
                        return_type: 'string',
                        default_value: null,
                        rules: [
                            {
                                ...split,
                                id: 'rule-split',
                                experiment_id: null,
                                holdout: { id: null, seed: 'holdout-seed-must-not-render', exclusion_percentage: 5 },
                            },
                            {
                                ...split,
                                id: 'rule-linked',
                                paused: false,
                                experiment_id: 12,
                                holdout: { id: 3, seed: 'holdout-seed-must-not-render', exclusion_percentage: 10 },
                            },
                        ],
                    }}
                />
            </Provider>
        )

        const [splitRow, linkedRow] = Array.from(container.querySelectorAll('tbody tr'))
        expect(splitRow).toHaveTextContent('Variant split')
        expect(splitRow).toHaveTextContent('Paused')
        expect(splitRow).toHaveTextContent('control33.34%"standard"')
        expect(splitRow).toHaveTextContent('compact66.66%"compact-layout"')
        expect(splitRow).toHaveTextContent('50%Miss: next rule')
        expect(splitRow).toHaveTextContent('Holds out 5%')
        expect(splitRow).not.toHaveTextContent('Experiment')
        expect(linkedRow).toHaveTextContent('Experiment #12')
        expect(linkedRow).toHaveTextContent('Holdout #3 excludes 10%')
        expect(linkedRow).not.toHaveTextContent('Paused')
        expect(container).not.toHaveTextContent('must-not-render')
    })
})
