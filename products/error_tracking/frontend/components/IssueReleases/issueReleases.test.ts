import { PropertyOperator } from '~/types'

import { PreviewPropertyFilter } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { IssueReleaseStrip, IssueReleaseStripKind, releasePropertyFilters } from './issueReleases'

describe('releasePropertyFilters', () => {
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
    const full = strip('release', { namespace: 'com.example.ios', version: '3.2.0', build: '1502' })

    it.each<[string, IssueReleaseStrip, boolean, PreviewPropertyFilter[]]>([
        [
            'scopes a full release to all three properties when the issue spans several apps',
            full,
            true,
            [exact('$app_namespace', 'com.example.ios'), exact('$app_version', '3.2.0'), exact('$app_build', '1502')],
        ],
        [
            'skips the namespace when the issue has a single app',
            full,
            false,
            [exact('$app_version', '3.2.0'), exact('$app_build', '1502')],
        ],
        [
            'keeps a namespace-only release distinct from missing release data',
            strip('release', { namespace: 'com.example.ios', version: null, build: null }),
            true,
            [exact('$app_namespace', 'com.example.ios'), notSet('$app_version'), notSet('$app_build')],
        ],
        [
            'filters missing release data on every property being unset',
            strip('unattributed', null),
            true,
            [notSet('$app_namespace'), notSet('$app_version'), notSet('$app_build')],
        ],
        ['cannot filter the folded "other" strip', strip('other', null), true, []],
    ])('%s', (_name, input, scopeToNamespace, expected) => {
        expect(releasePropertyFilters(input, scopeToNamespace)).toEqual(expected)
    })
})
