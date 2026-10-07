import { FEATURE_FLAGS } from 'lib/constants'

import { FeatureFlagConfig } from '~/types'

import {
    featureFlagConfigFormat,
    featureFlagConfigFormatLabel,
    isRulesV2EditableConfig,
    rowVersionToken,
} from './featureFlagConfigFormat'

const SPLIT_RULE = {
    id: 'rule-split',
    rule_type: 'experiment',
    targeting: { properties: [] },
    experiment_id: null,
    paused: false,
    rollout_percentage: 100,
    on_rollout_miss: 'continue',
    assignment_algorithm: 'sha1_60_v1',
    seed: 'split-seed',
    variants: [
        { key: 'control', weight: 50, value: 'standard' },
        { key: 'test', weight: 50, value: 'compact' },
    ],
}

const stringFlag = (rule: Record<string, unknown>, config: Record<string, unknown> = {}): FeatureFlagConfig =>
    ({
        version: 2,
        return_type: 'string',
        default_value: null,
        rules: [{ ...SPLIT_RULE, ...rule }],
        ...config,
    }) as FeatureFlagConfig

describe('featureFlagConfigFormat', () => {
    it.each([
        [undefined, 'v1', 'Config v1'],
        [{ groups: [] }, 'v1', 'Config v1'],
        [{ version: 1, groups: [] }, 'v1', 'Config v1'],
        [{ version: 2, return_type: 'boolean', default_value: false, rules: [] }, 'v2', 'Rules v2'],
        [{ version: 3 }, 'unsupported', 'Config v3 (unsupported)'],
        [{ version: null }, 'unsupported', 'Unsupported config'],
        [{ version: '2' }, 'unsupported', 'Unsupported config'],
    ])('reads %j as %s', (filters, format, label) => {
        expect(featureFlagConfigFormat(filters as FeatureFlagConfig | undefined)).toBe(format)
        expect(featureFlagConfigFormatLabel(filters as FeatureFlagConfig | undefined)).toBe(label)
    })

    it.each([
        ['a v1 row', { filters: { groups: [] }, version: 4 }, {}],
        ['a v2 row', { filters: { version: 2 } as FeatureFlagConfig, version: 4 }, { version: 4 }],
        ['an unsupported row', { filters: { version: 3 }, version: 4 }, { version: 4 }],
        ['a v2 row written before versioning', { filters: { version: 2 } as FeatureFlagConfig, version: null }, {}],
    ])('sends the row version only for a row outside v1: %s', (_, flag, expected) => {
        expect(rowVersionToken(flag)).toEqual(expected)
    })

    const EDITOR_ON = { [FEATURE_FLAGS.FEATURE_FLAG_RULES_V2_EDITOR]: true }

    it.each([
        ['a variant split without an experiment', stringFlag({}), true],
        [
            'a variant split with a holdout of its own',
            stringFlag({ holdout: { id: null, seed: 'holdout-seed', exclusion_percentage: 5 } }),
            true,
        ],
        [
            'a boolean variant split',
            stringFlag(
                { variants: [{ key: 'a', weight: 100, value: true }] },
                { return_type: 'boolean', default_value: false }
            ),
            true,
        ],
        ['a linked experiment', stringFlag({ experiment_id: 12 }), false],
        ['a shared holdout', stringFlag({ holdout: { id: 3, seed: 'holdout-seed', exclusion_percentage: 5 } }), false],
        ['group assignment', stringFlag({}, { aggregation_group_type_index: 0 }), false],
        ['a variant value of another type', stringFlag({ variants: [{ key: 'a', weight: 100, value: 1 }] }), false],
        [
            'a number return type',
            stringFlag(
                { variants: [{ key: 'a', weight: 100, value: 1 }] },
                { return_type: 'number', default_value: 1 }
            ),
            false,
        ],
        ['an unknown rule type', stringFlag({ rule_type: 'future_rule' }), false],
    ])('decides whether a flag with %s opens the editor', (_, filters, editable) => {
        expect(isRulesV2EditableConfig(filters, EDITOR_ON)).toBe(editable)
        expect(isRulesV2EditableConfig(filters, {})).toBe(false)
    })
})
