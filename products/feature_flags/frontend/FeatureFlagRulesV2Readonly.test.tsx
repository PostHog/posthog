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

    it('labels every experiment rule "Experiment" and shows its variants, pause and holdout', () => {
        const experimentRule = {
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
                                ...experimentRule,
                                id: 'rule-paused',
                                holdout: { seed: 'holdout-seed-must-not-render', exclusion_percentage: 5 },
                            },
                            { ...experimentRule, id: 'rule-running', paused: false },
                        ],
                    }}
                />
            </Provider>
        )

        const [pausedRow, runningRow] = Array.from(container.querySelectorAll('tbody tr'))
        expect(pausedRow).toHaveTextContent('Experiment')
        expect(pausedRow).toHaveTextContent('Paused')
        expect(pausedRow).toHaveTextContent('control33.34%"standard"')
        expect(pausedRow).toHaveTextContent('compact66.66%"compact-layout"')
        expect(pausedRow).toHaveTextContent('50%Miss: next rule')
        expect(pausedRow).toHaveTextContent('Holdout excludes 5%')
        expect(runningRow).toHaveTextContent('Experiment')
        expect(runningRow).not.toHaveTextContent('Paused')
        expect(runningRow).not.toHaveTextContent('Holdout')
        expect(container).not.toHaveTextContent('must-not-render')
    })
})
