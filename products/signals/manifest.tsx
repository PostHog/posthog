import { ProductManifest } from '../../frontend/src/types'
import type { InboxTabKey } from './frontend/inbox/types'

export const manifest: ProductManifest = {
    name: 'Signals',
    urls: {
        // Inbox 2.0 tab-first routing: /inbox, /inbox/<tab>, /inbox/<tab>/<reportId>.
        inbox: (tab?: InboxTabKey | ':tab'): string => `/inbox${tab ? `/${tab}` : ''}`,
        inboxReport: (tab: InboxTabKey | ':tab', reportId: string | ':reportId'): string => `/inbox/${tab}/${reportId}`,
        // Scout detail surface, full-width over the inbox list (the fleet section lives in the Configuration tab).
        // An optional finding id deep-links straight to one emitted finding (best-effort: only resolves while
        // that finding is still in the scout's recent runs window).
        inboxScout: (skillName: string | ':skillName', findingId?: string | ':findingId'): string => {
            const segment = findingId
                ? `/${findingId === ':findingId' ? findingId : encodeURIComponent(findingId)}`
                : ''
            return `/inbox/scouts/${skillName}${segment}`
        },
        // Scout fleet memory (scratchpad) browse/search surface, reached from the fleet-memory callout.
        inboxScratchpad: (): string => '/inbox/scouts/scratchpad',
        // Cross-fleet findings browse/search surface, reached from the scout-findings callout.
        inboxFindings: (): string => '/inbox/scouts/findings',
        // Mock-data-only redesign preview of the inbox (URL-only, no sidebar entry).
        v2Inbox: (): string => '/v2/inbox',
        v2Focus: (): string => '/v2/inbox/focus',
        v2Report: (id: string | ':id'): string => `/v2/report/${id}`,
        v2Resolved: (id: string | ':id'): string => `/v2/report/${id}/resolved`,
        v2Monitor: (id: string | ':id'): string => `/v2/report/${id}/monitor`,
    },
    scenes: {
        Inbox: {
            name: 'Inbox',
            import: () => import('./frontend/inbox/InboxScene'),
            projectBased: true,
            description: 'Actionable reports automatically generated from user session analysis and other signals.',
        },
        V2Inbox: {
            name: 'Inbox v2',
            import: () => import('./frontend/v2/V2InboxScene'),
            projectBased: true,
            description: 'Mock-data preview of the inbox redesign.',
        },
        V2Focus: {
            name: 'Focus mode',
            import: () => import('./frontend/v2/V2FocusScene'),
            projectBased: true,
            layout: 'app-full-scene-height',
        },
        V2Report: {
            name: 'Report v2',
            import: () => import('./frontend/v2/V2ReportScene'),
            projectBased: true,
        },
        V2Resolved: {
            name: 'Resolved report v2',
            import: () => import('./frontend/v2/V2ResolvedScene'),
            projectBased: true,
        },
        V2Monitor: {
            name: 'Fix monitor v2',
            import: () => import('./frontend/v2/V2MonitorScene'),
            projectBased: true,
        },
    },
    routes: {
        '/inbox': ['Inbox', 'inbox'],
        '/inbox/:tab': ['Inbox', 'inbox'],
        // Static memory and findings routes, registered before `:skillName` so they aren't read as scout names.
        '/inbox/scouts/scratchpad': ['Inbox', 'inbox'],
        '/inbox/scouts/findings': ['Inbox', 'inbox'],
        // Registered before the generic report route: both are two-segment `/inbox/x/y` shapes.
        '/inbox/scouts/:skillName': ['Inbox', 'inbox'],
        // Deep-link to a single scout finding: the bare scout route plus a trailing `/<finding>` segment.
        '/inbox/scouts/:skillName/:findingId': ['Inbox', 'inbox'],
        '/inbox/:tab/:reportId': ['Inbox', 'inbox'],
        '/v2/inbox': ['V2Inbox', 'v2Inbox'],
        '/v2/inbox/focus': ['V2Focus', 'v2Focus'],
        '/v2/report/:id': ['V2Report', 'v2Report'],
        '/v2/report/:id/resolved': ['V2Resolved', 'v2Resolved'],
        '/v2/report/:id/monitor': ['V2Monitor', 'v2Monitor'],
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
