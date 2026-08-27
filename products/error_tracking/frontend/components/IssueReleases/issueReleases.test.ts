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
    ])('%s', (_name, input, expected) => {
        expect(releasePropertyFilters(input)).toEqual(expected)
    })
})
