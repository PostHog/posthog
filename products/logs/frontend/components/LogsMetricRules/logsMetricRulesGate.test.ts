import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { matchesFlagDefinition } from 'scenes/settings/flagGating'

import { LOGS_METRIC_RULES_FLAGS, logsMetricRulesEnabled } from './logsMetricRulesGate'

const METRIC_RULES = FEATURE_FLAGS.LOGS_METRIC_RULES
const METRICS = FEATURE_FLAGS.METRICS

describe('logsMetricRulesEnabled', () => {
    it.each([
        ['both flags on', { [METRIC_RULES]: true, [METRICS]: true }, true],
        ['only logs-metric-rules on', { [METRIC_RULES]: true }, false],
        ['only metrics on', { [METRICS]: true }, false],
        ['neither on', {}, false],
    ])('%s', (_name, featureFlags, expected) => {
        expect(logsMetricRulesEnabled(featureFlags as FeatureFlagsSet)).toBe(expected)
    })

    it('gates settings sections the same way', () => {
        expect(matchesFlagDefinition(LOGS_METRIC_RULES_FLAGS, { [METRIC_RULES]: true } as FeatureFlagsSet)).toBe(false)
        expect(matchesFlagDefinition(LOGS_METRIC_RULES_FLAGS, { [METRICS]: true } as FeatureFlagsSet)).toBe(false)
        expect(
            matchesFlagDefinition(LOGS_METRIC_RULES_FLAGS, {
                [METRIC_RULES]: true,
                [METRICS]: true,
            } as FeatureFlagsSet)
        ).toBe(true)
    })
})
