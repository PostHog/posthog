import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { PreviewPropertyFilter } from '../IssueFilterPreview/issueFilterPreviewLogic'
import {
    formatReleaseCount,
    IssueReleaseStrip,
    IssueReleaseStripKind,
    releasePropertyFilters,
    selectedAppNamespace,
} from './issueReleases'

describe('issueReleases', () => {
    const group = (...filters: object[]): UniversalFiltersGroup => ({
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: filters as UniversalFiltersGroup['values'] }],
    })
    const namespaceChip = (operator: PropertyOperator, value: string[]): object => ({
        key: '$app_namespace',
        type: PropertyFilterType.Event,
        operator,
        value,
    })

    it.each<[string, UniversalFiltersGroup, string | null]>([
        [
            'reads a single exact namespace',
            group(namespaceChip(PropertyOperator.Exact, ['com.example.ios'])),
            'com.example.ios',
        ],
        ['ignores other chips', group({ key: '$browser', type: PropertyFilterType.Event, value: ['Chrome'] }), null],
        ['ignores a multi-value chip', group(namespaceChip(PropertyOperator.Exact, ['a', 'b'])), null],
        ['ignores a non-exact operator', group(namespaceChip(PropertyOperator.IsNot, ['com.example.ios'])), null],
        ['handles an empty group', group(), null],
    ])('selectedAppNamespace %s', (_name, filterGroup, expected) => {
        expect(selectedAppNamespace(filterGroup)).toBe(expected)
    })

    it.each<[number, string, boolean, string]>([
        [5000, 'release', true, '5,000+ releases'],
        [4999, 'release', false, '4,999 releases'],
        [1, 'release', false, '1 release'],
        [12, 'other release', true, '12+ other releases'],
    ])('formatReleaseCount %s %s truncated=%s', (count, noun, truncated, expected) => {
        expect(formatReleaseCount(count, noun, truncated)).toBe(expected)
    })

    const emptySeries = { counts: [], total: 0, first_seen: null, last_seen: null }

    const strip = (
        kind: IssueReleaseStripKind,
        release: { namespace: string | null; version: string | null; build: string | null } | null
    ): IssueReleaseStrip => ({
        key: 'k',
        kind,
        series: emptySeries,
        release: release ? { ...emptySeries, ...release } : null,
        label: 'label',
        fullLabel: 'label',
        color: '#000',
    })

    const exact = (key: string, value: string): PreviewPropertyFilter => ({
        key,
        value,
        operator: PropertyOperator.Exact,
    })
    const notSet = (key: string): PreviewPropertyFilter => ({ key, value: null, operator: PropertyOperator.IsNotSet })
    it.each<[string, IssueReleaseStrip, PreviewPropertyFilter[]]>([
        [
            'filters on version and build, never on the namespace',
            strip('release', { namespace: 'com.example.ios', version: '3.2.0', build: '1502' }),
            [exact('$app_version', '3.2.0'), exact('$app_build', '1502')],
        ],
        [
            'filters an unversioned release on both properties being unset',
            strip('release', { namespace: 'com.example.ios', version: null, build: null }),
            [notSet('$app_version'), notSet('$app_build')],
        ],
        [
            'filters missing release data on both properties being unset',
            strip('unattributed', null),
            [notSet('$app_version'), notSet('$app_build')],
        ],
        ['cannot filter the folded "other" strip', strip('other', null), []],
    ])('releasePropertyFilters %s', (_name, input, expected) => {
        expect(releasePropertyFilters(input)).toEqual(expected)
    })
})
