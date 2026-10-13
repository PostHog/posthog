import { FeatureFlagConfig } from '~/types'

import { featureFlagConfigFormat, featureFlagConfigFormatLabel, rowVersionToken } from './featureFlagConfigFormat'

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
})
