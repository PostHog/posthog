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

    it('shows a holdout by its exclusion percentage but never its seed', () => {
        const config: FeatureFlagRulesV2Config = {
            ...CONFIG,
            rules: [
                {
                    id: 'rule-3',
                    rule_type: 'experiment',
                    targeting: { properties: [] },
                    value: true,
                    rollout_percentage: 100,
                    on_rollout_miss: 'continue',
                    assignment_algorithm: 'sha1_60_v1',
                    seed: 'seed-must-not-render',
                    paused: false,
                    variants: [
                        { key: 'control', weight: 50, value: false },
                        { key: 'test', weight: 50, value: true },
                    ],
                    holdout: { seed: 'holdout-seed-must-not-render', exclusion_percentage: 10 },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={config} />
            </Provider>
        )

        expect(container).toHaveTextContent('Holdout excludes 10%')
        expect(container).not.toHaveTextContent('seed-must-not-render')
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

    it('shows an experiment rule by its variants and paused state', () => {
        const config: FeatureFlagRulesV2Config = {
            ...CONFIG,
            rules: [
                {
                    id: 'rule-2',
                    rule_type: 'experiment',
                    targeting: { properties: [] },
                    value: true,
                    rollout_percentage: 100,
                    on_rollout_miss: 'continue',
                    assignment_algorithm: 'sha1_60_v1',
                    seed: 'seed-must-not-render',
                    paused: true,
                    variants: [
                        { key: 'control', weight: 50, value: false },
                        { key: 'test', weight: 50, value: true },
                    ],
                },
            ],
        }
        const { container } = render(
            <Provider>
                <FeatureFlagRulesV2Readonly config={config} />
            </Provider>
        )

        expect(container).toHaveTextContent('Paused')
        expect(container).toHaveTextContent('control')
        expect(container).not.toHaveTextContent('seed-must-not-render')
    })
})
