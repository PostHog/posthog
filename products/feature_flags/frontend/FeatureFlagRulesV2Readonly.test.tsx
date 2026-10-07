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
})
