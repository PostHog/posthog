import { useValues } from 'kea'

import { FEATURE_FLAGS, type FeatureFlagLookupKey } from 'lib/constants'
import { type FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

/**
 * A rule only pays off in the Metrics product — that is the one place its output can be read.
 * So the logs flag alone is not enough to author one: without the Metrics alpha the author gets a
 * metric with no viewer. Every surface requires both flags, and the backend enforces the same pair.
 * Settings sections take the array directly, because `matchesFlagDefinition` ANDs its conditions.
 */
export const LOGS_METRIC_RULES_FLAGS: FeatureFlagLookupKey[] = [LogsFeatureFlagKeys.metricRules, 'METRICS']

export function logsMetricRulesEnabled(featureFlags: FeatureFlagsSet): boolean {
    return LOGS_METRIC_RULES_FLAGS.every((flag) => !!featureFlags[FEATURE_FLAGS[flag]])
}

export function useLogsMetricRulesEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return logsMetricRulesEnabled(featureFlags)
}
