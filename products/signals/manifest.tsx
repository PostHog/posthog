import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'
import type { InboxTabKey } from './frontend/inbox/types'

export const manifest: ProductManifest = {
    name: 'Signals',
    urls: {
        // Self-driving tab-first routing: /self-driving, /self-driving/<tab>, /self-driving/<tab>/<reportId>.
        selfDriving: (tab?: InboxTabKey | ':tab'): string => `/self-driving${tab ? `/${tab}` : ''}`,
        selfDrivingReport: (tab: InboxTabKey | ':tab', reportId: string | ':reportId'): string =>
            `/self-driving/${tab}/${reportId}`,
        // Scout detail surface, full-width over the report list (the fleet section lives in the Configuration tab).
        // An optional finding id deep-links straight to one emitted finding (best-effort: only resolves while
        // that finding is still in the scout's recent runs window).
        selfDrivingScout: (skillName: string | ':skillName', findingId?: string | ':findingId'): string => {
            const segment = findingId
                ? `/${findingId === ':findingId' ? findingId : encodeURIComponent(findingId)}`
                : ''
            return `/self-driving/scouts/${skillName}${segment}`
        },
        // Scout fleet memory (scratchpad) browse/search surface, reached from the fleet-memory callout.
        selfDrivingScratchpad: (): string => '/self-driving/scouts/scratchpad',
        // Cross-fleet findings browse/search surface, reached from the scout-findings callout.
        selfDrivingFindings: (): string => '/self-driving/scouts/findings',
    },
    scenes: {
        SelfDriving: {
            name: 'Self-driving',
            import: () => import('./frontend/inbox/InboxScene'),
            projectBased: true,
            description: 'Actionable reports automatically generated from user session analysis and other signals.',
        },
    },
    routes: {
        '/self-driving': ['SelfDriving', 'selfDriving'],
        '/self-driving/:tab': ['SelfDriving', 'selfDriving'],
        // Static memory and findings routes, registered before `:skillName` so they aren't read as scout names.
        '/self-driving/scouts/scratchpad': ['SelfDriving', 'selfDriving'],
        '/self-driving/scouts/findings': ['SelfDriving', 'selfDriving'],
        // Registered before the generic report route: both are two-segment `/self-driving/x/y` shapes.
        '/self-driving/scouts/:skillName': ['SelfDriving', 'selfDriving'],
        // Deep-link to a single scout finding: the bare scout route plus a trailing `/<finding>` segment.
        '/self-driving/scouts/:skillName/:findingId': ['SelfDriving', 'selfDriving'],
        '/self-driving/:tab/:reportId': ['SelfDriving', 'selfDriving'],
    },
    redirects: {
        // Old /inbox/* links (bookmarks, Slack, email) keep working after the rename to /self-driving.
        '/inbox': (_params, searchParams, hashParams) => combineUrl(urls.selfDriving(), searchParams, hashParams).url,
        '/inbox/scouts/scratchpad': (_params, searchParams, hashParams) =>
            combineUrl(urls.selfDrivingScratchpad(), searchParams, hashParams).url,
        '/inbox/scouts/findings': (_params, searchParams, hashParams) =>
            combineUrl(urls.selfDrivingFindings(), searchParams, hashParams).url,
        '/inbox/scouts/:skillName': (params, searchParams, hashParams) =>
            combineUrl(urls.selfDrivingScout(params.skillName), searchParams, hashParams).url,
        '/inbox/scouts/:skillName/:findingId': (params, searchParams, hashParams) =>
            combineUrl(urls.selfDrivingScout(params.skillName, params.findingId), searchParams, hashParams).url,
        '/inbox/:tab/:reportId': (params, searchParams, hashParams) =>
            combineUrl(urls.selfDrivingReport(params.tab, params.reportId), searchParams, hashParams).url,
        '/inbox/:tab': (params, searchParams, hashParams) =>
            combineUrl(urls.selfDriving(params.tab), searchParams, hashParams).url,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
