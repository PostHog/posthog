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
        investigationsDemo: (): string => '/investigations-demo',
        investigationsDemoFocus: (): string => '/investigations-demo/focus',
        investigationsDemoReport: (id: string | ':id'): string => `/investigations-demo/report/${id}`,
        investigationsDemoResolved: (id: string | ':id'): string => `/investigations-demo/report/${id}/resolved`,
        investigationsDemoMonitor: (): string => '/investigations-demo/monitor',
    },
    scenes: {
        Inbox: {
            name: 'Inbox',
            import: () => import('./frontend/inbox/InboxScene'),
            projectBased: true,
            description: 'Actionable reports automatically generated from user session analysis and other signals.',
        },
        InvestigationsDemo: {
            name: 'Investigations demo',
            import: () => import('./frontend/investigations-demo/InvestigationsInboxScene'),
            projectBased: true,
            description: 'Mock-data preview of the investigations inbox redesign.',
        },
        InvestigationsDemoFocus: {
            name: 'Focus mode demo',
            import: () => import('./frontend/investigations-demo/InvestigationsFocusScene'),
            projectBased: true,
            layout: 'app-full-scene-height',
        },
        InvestigationsDemoReport: {
            name: 'Investigation report demo',
            import: () => import('./frontend/investigations-demo/InvestigationsReportScene'),
            projectBased: true,
        },
        InvestigationsDemoResolved: {
            name: 'Resolved report demo',
            import: () => import('./frontend/investigations-demo/InvestigationsResolvedScene'),
            projectBased: true,
        },
        InvestigationsDemoMonitor: {
            name: 'Fix monitor demo',
            import: () => import('./frontend/investigations-demo/InvestigationsMonitorScene'),
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
        '/investigations-demo': ['InvestigationsDemo', 'investigationsDemo'],
        '/investigations-demo/focus': ['InvestigationsDemoFocus', 'investigationsDemoFocus'],
        '/investigations-demo/monitor': ['InvestigationsDemoMonitor', 'investigationsDemoMonitor'],
        '/investigations-demo/report/:id': ['InvestigationsDemoReport', 'investigationsDemoReport'],
        '/investigations-demo/report/:id/resolved': ['InvestigationsDemoResolved', 'investigationsDemoResolved'],
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
