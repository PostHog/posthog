import { ProductManifest } from '../../frontend/src/types'
import type { InboxTabKey } from './frontend/inbox/types'

export const manifest: ProductManifest = {
    name: 'Signals',
    urls: {
        // Tab-first routing: /inbox, /inbox/<tab>, /inbox/<tab>/<reportId>.
        inbox: (tab?: InboxTabKey | ':tab'): string => `/inbox${tab ? `/${tab}` : ''}`,
        inboxReport: (tab: InboxTabKey | ':tab', reportId: string | ':reportId'): string => `/inbox/${tab}/${reportId}`,
        // Triage mode: the Needs-a-decision queue one report at a time, full-width over the list.
        inboxTriage: (): string => '/inbox/reports/triage',
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
        // Project-wide list of scout and signal-pipeline runs, reached from the roster footer.
        inboxRuns: (): string => '/inbox/scouts/runs',
    },
    scenes: {
        Inbox: {
            name: 'Inbox',
            import: () => import('./frontend/inbox/InboxScene'),
            projectBased: true,
            description: 'Actionable reports automatically generated from user session analysis and other signals.',
        },
    },
    routes: {
        '/inbox': ['Inbox', 'inbox'],
        '/inbox/:tab': ['Inbox', 'inbox'],
        // Static panel routes, registered before `:skillName` / `:reportId` so they aren't read as ids.
        '/inbox/scouts/scratchpad': ['Inbox', 'inbox'],
        '/inbox/scouts/findings': ['Inbox', 'inbox'],
        '/inbox/scouts/runs': ['Inbox', 'inbox'],
        '/inbox/reports/triage': ['Inbox', 'inbox'],
        // Registered before the generic report route: both are two-segment `/inbox/x/y` shapes.
        '/inbox/scouts/:skillName': ['Inbox', 'inbox'],
        // Deep-link to a single scout finding: the bare scout route plus a trailing `/<finding>` segment.
        '/inbox/scouts/:skillName/:findingId': ['Inbox', 'inbox'],
        '/inbox/:tab/:reportId': ['Inbox', 'inbox'],
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
