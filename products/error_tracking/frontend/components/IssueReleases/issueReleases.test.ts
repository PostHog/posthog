import { PropertyOperator } from '~/types'

import { IssueReleaseStrip, IssueReleaseStripKind, ReleaseFilter, releaseFilters } from './issueReleases'

describe('releaseFilters', () => {
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

    it.each<[string, IssueReleaseStrip, ReleaseFilter[]]>([
        [
            'scopes a namespaced version to both properties',
            strip('release', { namespace: 'com.example.ios', version: '3.2.0', build: '1502' }),
            [
                { key: '$app_version', value: '3.2.0', operator: PropertyOperator.Exact },
                { key: '$app_namespace', value: 'com.example.ios', operator: PropertyOperator.Exact },
            ],
        ],
        [
            'keeps a namespace-only release distinct from missing release data',
            strip('release', { namespace: 'com.example.ios', version: null, build: null }),
            [
                { key: '$app_version', value: null, operator: PropertyOperator.IsNotSet },
                { key: '$app_namespace', value: 'com.example.ios', operator: PropertyOperator.Exact },
            ],
        ],
        [
            'filters on version alone when the release has no namespace',
            strip('release', { namespace: null, version: '3.2.0', build: null }),
            [{ key: '$app_version', value: '3.2.0', operator: PropertyOperator.Exact }],
        ],
        [
            'filters missing release data on version only',
            strip('unattributed', null),
            [{ key: '$app_version', value: null, operator: PropertyOperator.IsNotSet }],
        ],
        ['cannot filter the folded "other" strip', strip('other', null), []],
    ])('%s', (_name, input, expected) => {
        expect(releaseFilters(input)).toEqual(expected)
    })
})
