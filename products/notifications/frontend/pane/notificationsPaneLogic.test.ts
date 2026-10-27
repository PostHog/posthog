import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InAppNotification } from '~/types'

import { NotificationEventApi } from '../generated/api.schemas'
import { notificationsPaneLogic } from './notificationsPaneLogic'

const SUMMARY = { count: 1, direct_count: 1, has_critical: false }

function makeNotification(overrides: Partial<NotificationEventApi> = {}): NotificationEventApi {
    return {
        id: 'n1',
        team_id: 997,
        notification_type: 'comment_mention',
        priority: 'normal',
        title: 'Ana Silva mentioned you',
        body: '',
        read: false,
        read_at: null,
        archived: false,
        target_type: 'user',
        target_id: '1',
        resource_type: null,
        resource_id: '',
        source_url: '/insights/abc',
        source_type: null,
        source_id: null,
        metadata: null,
        created_at: '2026-10-27T12:00:00Z',
        ...overrides,
    }
}

function asLiveEvent(notification: NotificationEventApi): InAppNotification {
    return { ...notification, metadata: null }
}

describe('notificationsPaneLogic', () => {
    let logic: ReturnType<typeof notificationsPaneLogic.build>
    let requests: URL[]
    let requestBodies: unknown[]
    let archiveStatus: number

    beforeEach(() => {
        requests = []
        requestBodies = []
        archiveStatus = 200
        const record = async ({ request }: { request: Request }): Promise<void> => {
            requests.push(new URL(request.url))
            if (request.method === 'POST') {
                requestBodies.push(await request.json().catch(() => null))
            }
        }
        useMocks({
            get: {
                '/api/projects/:team/notifications/': async (req) => {
                    await record(req)
                    return [200, { count: 0, results: [], next: null, previous: null, next_cursor: null }]
                },
                '/api/projects/:team/notifications/unread_count/': async (req) => {
                    await record(req)
                    return [200, SUMMARY]
                },
            },
            post: {
                '/api/projects/:team/notifications/:id/archive/': async (req) => {
                    await record(req)
                    return [archiveStatus, { status: 'ok' }]
                },
                '/api/projects/:team/notifications/archive_all/': async (req) => {
                    await record(req)
                    return [200, { updated: 2, notification_ids: ['read-1', 'unread-1'] }]
                },
                '/api/projects/:team/notifications/unarchive_bulk/': async (req) => {
                    await record(req)
                    return [200, { updated: 1 }]
                },
                '/api/projects/:team/notifications/mark_all_read/': async (req) => {
                    await record(req)
                    return [200, { updated: 1 }]
                },
            },
        })
        initKeaTests()
        logic = notificationsPaneLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    const lastRequestTo = (path: string): URL | undefined =>
        [...requests].reverse().find((url) => url.pathname.endsWith(path))

    it('sends the filters to the list endpoint', async () => {
        await expectLogic(logic, () => {
            logic.actions.setFilters({ read: 'unread', category: 'approvals', project: 'current' })
        }).toDispatchActions(['setItems'])

        const params = lastRequestTo('/notifications/')?.searchParams
        expect(params?.get('read')).toBe('false')
        expect(params?.get('notification_type')).toBe('approval_requested,approval_resolved')
        expect(params?.get('team_id')).toBe(String(teamLogic.values.currentTeamId))
        expect(params?.get('archived')).toBe('false')
    })

    it('inserts a live arrival while the list is idle, unless the filters exclude it', async () => {
        const live = sidePanelNotificationsLogic.actions.notificationReceived

        live(asLiveEvent(makeNotification({ id: 'mention' })))
        expect(logic.values.items.map((item) => item.id)).toEqual(['mention'])

        await expectLogic(logic, () => {
            logic.actions.setFilters({ read: 'all', category: 'approvals', project: 'all' })
        }).toDispatchActions(['setItems'])
        live(asLiveEvent(makeNotification({ id: 'another-mention' })))

        expect(logic.values.items).toEqual([])
    })

    it('counts a live arrival instead of inserting it while the person is reading', () => {
        logic.actions.setItems([makeNotification({ id: 'existing' })], null)
        logic.actions.setListIdle(false)

        sidePanelNotificationsLogic.actions.notificationReceived(asLiveEvent(makeNotification({ id: 'new' })))

        expect(logic.values.items.map((item) => item.id)).toEqual(['existing'])
        expect(logic.values.newCount).toBe(1)
    })

    it('undoing a group archive restores the read state each notification had', async () => {
        const group = [
            makeNotification({ id: 'unread-1', notification_type: 'pipeline_failure', resource_id: 'be-1' }),
            makeNotification({ id: 'read-1', notification_type: 'pipeline_failure', resource_id: 'be-1', read: true }),
        ]
        logic.actions.setItems(group, null)
        const [entry] = logic.values.entries

        await expectLogic(logic, () => logic.actions.archive(entry)).toDispatchActions(['setLastArchived'])
        expect(logic.values.items).toEqual([])
        await expectLogic(logic, () => logic.actions.undoArchive()).toDispatchActions(['loadNotifications'])

        expect(requestBodies).toContainEqual({ notification_ids: ['read-1'], mark_unread: false })
        expect(requestBodies).toContainEqual({ notification_ids: ['unread-1'], mark_unread: true })
    })

    it('puts the row back when the archive request fails', async () => {
        archiveStatus = 500
        logic.actions.setItems([makeNotification({ id: 'keep-me' })], null)

        await expectLogic(logic, () => logic.actions.archive(logic.values.entries[0])).toDispatchActions([
            'removeItems',
            'setItems',
        ])

        expect(logic.values.items.map((item) => item.id)).toEqual(['keep-me'])
    })

    it('marks only the current view as read', async () => {
        logic.actions.setFilters({ read: 'all', category: 'any', project: 'current' })

        await expectLogic(logic, () => logic.actions.markAllRead()).toDispatchActions(['loadSummary', 'setSummary'])

        const params = lastRequestTo('/mark_all_read/')?.searchParams
        expect(params?.get('team_id')).toBe(String(teamLogic.values.currentTeamId))
        expect(params?.has('archived')).toBe(false)
    })
})
