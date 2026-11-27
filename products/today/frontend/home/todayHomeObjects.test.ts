import { StoredAutomateRecent } from '~/layout/today/todayAutomateRecents'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { homeObjectRows, homeRecentEntries } from './todayHomeObjects'

const at = (minute: number): string => new Date(Date.UTC(2026, 10, 26, 12, minute)).toISOString()
const ms = (minute: number): number => Date.parse(at(minute))

const dashboard = (ref: string, minute: number): FileSystemEntry => ({
    id: `dashboard-${ref}`,
    path: `Dashboard ${ref}`,
    type: 'dashboard',
    ref,
    href: `/dashboard/${ref}`,
    last_viewed_at: at(minute),
})

const workflow: StoredAutomateRecent = {
    type: 'workflow',
    name: 'Time capsule',
    href: '/workflows/1/workflow',
    viewedAt: ms(30),
}
const broadcast: StoredAutomateRecent = {
    type: 'broadcast',
    name: 'Launch email',
    href: '/broadcasts/2',
    viewedAt: ms(5),
}
const destination: StoredAutomateRecent = {
    type: 'hog_function/destination',
    name: 'Webhook',
    href: '/functions/3',
    viewedAt: ms(40),
}

describe('homeRecentEntries', () => {
    it('lists workflows and broadcasts with the server recents, newest first', () => {
        const entries = homeRecentEntries([dashboard('a', 20), dashboard('b', 10)], false, [workflow, broadcast])
        expect(entries.map((entry) => entry.href)).toEqual([
            '/workflows/1/workflow',
            '/dashboard/a',
            '/dashboard/b',
            '/broadcasts/2',
        ])
    })

    it('leaves destinations to the server', () => {
        expect(homeRecentEntries([], false, [destination]).map((entry) => entry.href)).toEqual([])
    })

    it('holds back a recent older than a full server page', () => {
        const entries = homeRecentEntries([dashboard('a', 20), dashboard('b', 10)], true, [workflow, broadcast])
        expect(entries.map((entry) => entry.href)).toEqual(['/workflows/1/workflow', '/dashboard/a', '/dashboard/b'])
    })

    it('puts a recent saved without a view time last', () => {
        const entries = homeRecentEntries([dashboard('a', 20)], false, [{ ...workflow, viewedAt: undefined }])
        expect(entries.map((entry) => entry.href)).toEqual(['/dashboard/a', '/workflows/1/workflow'])
    })

    it('gives a workflow and a broadcast a named row with their type', () => {
        const rows = homeObjectRows(homeRecentEntries([], false, [workflow, broadcast]))
        expect(rows.map(({ name, href, typeCopy }) => ({ name, href, label: typeCopy.label }))).toEqual([
            { name: 'Time capsule', href: '/workflows/1/workflow', label: 'Workflow' },
            { name: 'Launch email', href: '/broadcasts/2', label: 'Broadcast' },
        ])
    })
})
