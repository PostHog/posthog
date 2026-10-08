import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { todaySessionMenuLogic } from '~/layout/today/todaySessionMenuLogic'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { TaskListItemApi } from '../generated/api.schemas'
import { DEFAULT_SPACE_FEED_FILTERS, SpaceFeedFilters, SpaceFeedType } from './spaceFeedEntries'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'
import {
    AutoArchiveSelection,
    SPACE_CANVASES_MAX,
    SpaceFeedStatus,
    SpaceTab,
    spaceComposerPanelId,
    spaceSceneLogic,
} from './spaceSceneLogic'

describe('spaceSceneLogic', () => {
    let sessionSpace = 'space-a'
    let starredIds: string[] = []
    let starRequests: { id: string; starred: boolean }[] = []
    let spacePatches: Record<string, unknown>[] = []
    let memberUpdates: number[][] = []
    let spaceCanvases: CanvasApi[] = []
    let canvasRequests: (string | null)[] = []
    let canvasStatus = 200
    let canvasPatches: { id: string; body: unknown }[] = []
    let canvasDeletes: string[] = []

    beforeEach(() => {
        sessionSpace = 'space-a'
        starredIds = []
        starRequests = []
        spacePatches = []
        memberUpdates = []
        spaceCanvases = []
        canvasRequests = []
        canvasStatus = 200
        canvasPatches = []
        canvasDeletes = []
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const channel = params.get('channel')
                    canvasRequests.push(channel)
                    const all = channel === 'space-a' ? spaceCanvases : []
                    const offset = Number(params.get('offset') ?? 0)
                    const results = all.slice(offset, offset + Number(params.get('limit') ?? all.length))
                    const next = offset + results.length < all.length ? 'https://example.com/next' : null
                    return [200, { results, count: all.length, next }]
                },
                '/api/projects/:team_id/task_channels/': () => [
                    200,
                    ['space-a', 'space-b'].map((id) => ({ id, name: id, starred: starredIds.includes(id) })),
                ],
                '/api/projects/:team_id/task_channels/:id/': ({ params }) => [
                    200,
                    {
                        id: params.id,
                        name: String(params.id),
                        system_role: null,
                        channel_type: 'public',
                        auto_archive_after_days: 7,
                        created_by: { id: 7, uuid: 'user-7', first_name: 'Ada', email: 'ada@example.com' },
                        github_integration: params.id === 'space-a' ? 3 : null,
                        repositories: params.id === 'space-a' ? ['acme/api', 'acme/web'] : [],
                    },
                ],
                '/api/projects/:team_id/task_channels/:id/members/': [
                    { id: 7, uuid: 'user-7', first_name: 'Ada', email: 'ada@example.com' },
                ],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const channel = new URL(request.url).searchParams.get('channel')
                    const results =
                        channel === sessionSpace
                            ? [{ id: 'task-1', title: 'Session', channel, archived: false, last_activity_at: null }]
                            : []
                    return [200, { results, count: results.length }]
                },
            },
            post: {
                '/api/projects/:team_id/task_channels/:id/star/': async ({ params, request }) => {
                    const { starred } = (await request.json()) as { starred: boolean }
                    starRequests.push({ id: String(params.id), starred })
                    starredIds = starred
                        ? [...starredIds, String(params.id)]
                        : starredIds.filter((id) => id !== params.id)
                    return [200, {}]
                },
            },
            put: {
                '/api/projects/:team_id/task_channels/:id/members/': async ({ request }) => {
                    const { user_ids } = (await request.json()) as { user_ids: number[] }
                    memberUpdates.push(user_ids)
                    return [200, user_ids.map((id) => ({ id }))]
                },
            },
            patch: {
                '/api/projects/:team_id/canvases/:id/': async ({ params, request }) => {
                    const body = (await request.json()) as { pinned: boolean }
                    canvasPatches.push({ id: String(params.id), body })
                    const canvas = spaceCanvases.find(({ id }) => id === params.id)
                    return [
                        canvasStatus,
                        { ...canvas, pinned_at: body.pinned ? '2026-09-30T09:00:00Z' : null } as CanvasApi,
                    ]
                },
                '/api/projects/:team_id/task_channels/:id/': async ({ params, request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    spacePatches.push(body)
                    return [200, { id: params.id, system_role: null, ...body }]
                },
                '/api/projects/:team_id/tasks/:id/': async ({ request }) => {
                    const body = (await request.json()) as { channel?: string }
                    sessionSpace = body.channel ?? sessionSpace
                    return [200, { id: 'task-1', channel: sessionSpace }]
                },
            },
            delete: {
                '/api/projects/:team_id/canvases/:id/': ({ params }) => {
                    canvasDeletes.push(String(params.id))
                    return [canvasStatus === 200 ? 204 : canvasStatus, null]
                },
            },
        })
        initKeaTests()
    })

    const canvasesNamed = (count: number): CanvasApi[] =>
        Array.from(
            { length: count },
            (_, index) =>
                ({
                    id: `c-${index}`,
                    name: `Canvas ${index}`,
                    pinned_at: null,
                    updated_at: '2026-09-28T11:00:00Z',
                    created_by: { id: 999 },
                }) as unknown as CanvasApi
        )

    const mountWithCanvases = async (canvases: CanvasApi[]): Promise<ReturnType<typeof spaceSceneLogic.build>> => {
        spaceCanvases = canvases
        spaceFeedViewLogic.mount()
        spaceFeedViewLogic.actions.setFilters(DEFAULT_SPACE_FEED_FILTERS)
        spaceFeedViewLogic.actions.setTypes(['canvas'])
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    it('drops a session from the feed when the row menu moves it to another space', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedItems.map((item) => item.id)).toEqual(['task-1'])

        todaySessionMenuLogic.actions.moveSession('task-1', 'space-b')
        await expectLogic(logic).toDispatchActions(['sessionUpdated', 'loadSessionsSuccess'])

        expect(logic.values.feedSections).toEqual([])
    })

    it.each([
        ['a new name', '  checkout ', [{ name: 'checkout' }], 'checkout', null, null],
        ['a blank name', '   ', [], 'space-a', '   ', 'Enter a name'],
        ['a name over the limit', 'x'.repeat(129), [], 'space-a', 'x'.repeat(129), 'Use 128 characters or fewer'],
        ['the saved name', 'space-a', [], 'space-a', null, null],
    ])(
        'renames once on Enter and blur for %s',
        async (_, draft, expectedPatches, expectedName, expectedDraft, expectedError) => {
            const logic = spaceSceneLogic({ id: 'space-a' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setNameDraft(draft)
            logic.actions.commitName()
            logic.actions.commitName()
            await expectLogic(logic).toFinishAllListeners()

            expect(spacePatches).toEqual(expectedPatches)
            expect(logic.values.space?.name).toBe(expectedName)
            expect(logic.values.nameDraft).toBe(expectedDraft)
            expect(logic.values.nameError).toBe(expectedError)
            expect(logic.values.savingSpace).toBe(false)
        }
    )

    it.each([
        [404, true],
        [500, false],
    ])('treats a %s space load as missing: %s', async (status, missing) => {
        useMocks({
            get: { '/api/projects/:team_id/task_channels/:id/': () => [status, { detail: 'Error' }] },
        })
        const logic = spaceSceneLogic({ id: 'space-gone' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSpaceFailure'])

        expect(logic.values.spaceMissing).toBe(missing)
        expect(logic.values.spaceUnavailable).toBe(true)
    })

    it.each([
        ['space-a', { integrationId: 3, repository: 'acme/api' }],
        ['space-b', undefined],
    ])('starts the new-session composer of %s on its first repository', async (id, expected) => {
        const logic = spaceSceneLogic({ id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.composerRepositoryConfig).toEqual(expected)
    })

    it.each([
        [
            'one repository is used most',
            [
                ['a', 'acme/web'],
                ['b', 'acme/api'],
                ['c', 'acme/api'],
            ],
            { a: 'acme/web', b: null, c: null },
        ],
        [
            'two repositories tie',
            [
                ['a', 'acme/web'],
                ['b', 'acme/api'],
            ],
            { a: null, b: 'acme/api' },
        ],
        [
            'a session has no repository',
            [
                ['a', null],
                ['b', 'acme/api'],
            ],
            { a: null, b: null },
        ],
        [
            'archived sessions use another repository',
            [
                ['a', 'acme/web'],
                ['b', 'acme/api', true],
                ['c', 'acme/api', true],
            ],
            { a: null, b: 'acme/api', c: 'acme/api' },
        ],
    ] as [string, [string, string | null, boolean?][], Record<string, string | null>][])(
        'names a card repository only when it is not the usual one, when %s',
        async (_, sessions, expected) => {
            const logic = spaceSceneLogic({ id: 'space-a' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.loadSessionsSuccess(
                sessions.map(([id, repository, archived = false]) => ({ id, repository, archived }) as TaskListItemApi)
            )

            expect(logic.values.feedRepositories).toEqual(expected)
        }
    )

    it.each<[string, Partial<SpaceFeedFilters>, SpaceFeedType[], string[]]>([
        ['nothing narrows it', {}, ['task', 'pr'], ['theirs', '#2', '#1', 'mine']],
        ['only PRs show', {}, ['pr'], ['#2', '#1']],
        ['it keeps my sessions', { createdBy: 'me' }, ['task', 'pr'], ['mine', '#1']],
        ['it keeps unread sessions', { status: 'unread' }, ['task', 'pr'], ['theirs', '#2', '#1']],
        ['it keeps pinned sessions', { pinned: 'pinned' }, ['task', 'pr'], ['mine', '#1']],
        ['it keeps local runs', { environment: 'local' }, ['task'], ['theirs']],
        ['canvases show', {}, ['task', 'canvas'], ['their canvas', 'theirs', 'my canvas', 'mine']],
        ['it keeps my canvases', { createdBy: 'me' }, ['canvas'], ['my canvas']],
        ['a session-only filter hides canvases', { status: 'unread' }, ['task', 'canvas'], ['theirs']],
    ])('lists the feed entries when %s', async (_, filters, types, expected) => {
        const pullRequest = (number: number): string => `https://github.com/acme/api/pull/${number}`
        spaceCanvases = [
            {
                id: 'c-1',
                name: 'my canvas',
                updated_at: '2026-09-28T11:00:00Z',
                created_by: { id: MOCK_DEFAULT_USER.id },
            },
            { id: 'c-2', name: 'their canvas', updated_at: '2026-09-28T13:00:00Z', created_by: { id: 999 } },
        ] as unknown as CanvasApi[]
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        spaceFeedViewLogic.actions.setFilters({ ...DEFAULT_SPACE_FEED_FILTERS, ...filters })
        spaceFeedViewLogic.actions.setTypes(types)
        await expectLogic(logic).toFinishAllListeners()
        todaySpacesLogic.actions.loadPinnedTasksSuccess([{ id: 'mine' } as TaskListItemApi])
        todaySpacesLogic.actions.loadTaskActivitySuccess([
            { id: 'activity', task_id: 'theirs', is_unread: true, latest_comment_id: null },
        ] as unknown as Parameters<typeof todaySpacesLogic.actions.loadTaskActivitySuccess>[0])

        logic.actions.loadSessionsSuccess([
            {
                id: 'mine',
                archived: false,
                last_activity_at: '2026-09-28T10:00:00Z',
                created_by: { id: MOCK_DEFAULT_USER.id },
                latest_run: { environment: 'cloud', output: { pr_url: pullRequest(1) } },
            },
            {
                id: 'theirs',
                archived: false,
                last_activity_at: '2026-09-28T12:00:00Z',
                created_by: { id: 999 },
                latest_run: { environment: 'local', output: { pr_url: pullRequest(2), pr_urls: [pullRequest(1)] } },
            },
        ] as unknown as TaskListItemApi[])

        const entries = logic.values.feedSections.flatMap((section) => section.entries)
        expect(
            entries.map((entry) =>
                entry.kind === 'pr'
                    ? `#${entry.pullRequest.number}`
                    : entry.kind === 'canvas'
                      ? entry.canvas.name
                      : entry.item.id
            )
        ).toEqual(expected)
    })

    it('loads the canvases once, when their type first shows', async () => {
        spaceFeedViewLogic.mount()
        spaceFeedViewLogic.actions.setTypes(['task'])
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(canvasRequests).toEqual([])

        spaceFeedViewLogic.actions.setTypes(['task', 'canvas'])
        await expectLogic(logic).toDispatchActions(['loadCanvasesSuccess'])
        spaceFeedViewLogic.actions.setTypes(['task'])
        spaceFeedViewLogic.actions.setTypes(['canvas'])
        await expectLogic(logic).toFinishAllListeners()

        expect(canvasRequests).toEqual(['space-a'])
    })

    it.each([
        ['one page', 30, 1, 30],
        ['every page', 120, 3, 120],
        ['no more than the cap', 450, 4, SPACE_CANVASES_MAX],
    ])('loads %s of a space’s canvases', async (_, total, expectedRequests, expectedCount) => {
        const logic = await mountWithCanvases(canvasesNamed(total))

        expect(canvasRequests).toHaveLength(expectedRequests)
        expect(logic.values.canvases?.map(({ id }) => id)).toEqual(canvasesNamed(expectedCount).map(({ id }) => id))
    })

    it.each<[string, string | null, number, string | null, string[]]>([
        ['pins a canvas', null, 200, '2026-09-30T09:00:00Z', ['c-0']],
        ['unpins a canvas', '2026-09-29T09:00:00Z', 200, null, []],
        ['restores the pin when saving fails', null, 500, null, []],
    ])('%s once from its menu', async (_, pinnedAt, status, expectedPinnedAt, expectedPinned) => {
        canvasStatus = status
        const logic = await mountWithCanvases([{ ...canvasesNamed(1)[0], pinned_at: pinnedAt }])

        logic.actions.toggleCanvasPinned('c-0')
        logic.actions.toggleCanvasPinned('c-0')
        expect(logic.values.canvasSections.pinned.length).toBe(pinnedAt ? 0 : 1)
        await expectLogic(logic).toFinishAllListeners()

        expect(canvasPatches).toEqual([{ id: 'c-0', body: { pinned: !pinnedAt } }])
        expect(logic.values.canvases?.[0].pinned_at).toBe(expectedPinnedAt)
        expect(logic.values.canvasSections.pinned.map(({ id }) => id)).toEqual(expectedPinned)
        expect(logic.values.pendingCanvasIds).toEqual([])
    })

    it.each<[string, number, string[], boolean]>([
        ['removes the canvas', 200, ['c-1'], false],
        ['keeps the canvas and the dialog when deleting fails', 500, ['c-0', 'c-1'], true],
    ])('%s after the delete is confirmed', async (_, status, expectedIds, dialogOpen) => {
        canvasStatus = status
        const logic = await mountWithCanvases(canvasesNamed(2))

        logic.actions.setCanvasDeleteTarget(logic.values.canvases![0])
        logic.actions.confirmCanvasDelete()
        logic.actions.confirmCanvasDelete()
        expect(logic.values.canvasDeleting).toBe(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(canvasDeletes).toEqual(['c-0'])
        expect(logic.values.canvases?.map(({ id }) => id)).toEqual(expectedIds)
        expect(logic.values.feedSections.flatMap((section) => section.entries)).toHaveLength(expectedIds.length)
        expect(logic.values.canvasDeleteTarget !== null).toBe(dialogOpen)
        expect(logic.values.canvasDeleting).toBe(false)
    })

    it.each<[string, SpaceTab, string[]]>([
        [urls.taskSpace('space-a'), 'feed', []],
        [urls.taskSpaceCanvases('space-a'), 'canvases', ['space-a']],
        [urls.taskSpaceSettings('space-a'), 'settings', []],
    ])('opens %s on the %s tab and loads its canvases: %j', async (url, tab, expectedRequests) => {
        spaceFeedViewLogic.mount()
        spaceFeedViewLogic.actions.setTypes(['task'])
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push(url)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeTab).toBe(tab)
        expect(canvasRequests).toEqual(expectedRequests)
    })

    it.each<[string, number, SpaceFeedType[], SpaceFeedStatus, string[]]>([
        ['sessions load', 200, ['task'], { sessions: 'ready', canvases: 'hidden' }, ['task-1']],
        ['sessions fail', 500, ['task', 'pr'], { sessions: 'failed', canvases: 'hidden' }, []],
        ['sessions fail beside canvases', 500, ['task', 'canvas'], { sessions: 'failed', canvases: 'ready' }, ['c-1']],
        ['only canvases show', 500, ['canvas'], { sessions: 'hidden', canvases: 'ready' }, ['c-1']],
    ])('reports each feed source apart when %s', async (_, sessionsStatus, types, expected, entryIds) => {
        if (sessionsStatus !== 200) {
            useMocks({ get: { '/api/projects/:team_id/tasks/': () => [sessionsStatus, { detail: 'Error' }] } })
        }
        spaceCanvases = [
            { id: 'c-1', name: 'Canvas', updated_at: '2026-09-28T11:00:00Z', created_by: { id: 999 } },
        ] as unknown as CanvasApi[]
        spaceFeedViewLogic.mount()
        spaceFeedViewLogic.actions.setFilters(DEFAULT_SPACE_FEED_FILTERS)
        spaceFeedViewLogic.actions.setTypes(types)
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()

        expect(logic.values.feedStatus.sessions).toBe(types.includes('task') ? 'loading' : 'hidden')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.feedStatus).toEqual(expected)
        expect(
            logic.values.feedSections.flatMap((section) =>
                section.entries.map((entry) => (entry.kind === 'canvas' ? entry.canvas.id : entry.key))
            )
        ).toEqual(entryIds)
    })

    it('opens a started session and lists it in the feed', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.sessionStarted('task-new')
        await expectLogic(logic).toDispatchActions(['loadSessions', 'loadSessionsSuccess'])

        expect(router.values.location.pathname).toMatch(/\/ai$/)
        expect(router.values.searchParams).toEqual({ task: 'task-new' })
    })

    it.each([
        ['clears a session once it opens', 200, '2026-09-30T11:00:00.000Z', '2026-09-30T12:00:00.000Z', []],
        [
            'clears activity stamped ahead of the local clock',
            200,
            '2026-09-30T12:05:00.000Z',
            '2026-09-30T12:05:00.000Z',
            [],
        ],
        [
            'restores unread when marking read fails',
            500,
            '2026-09-30T11:00:00.000Z',
            '2026-09-30T12:00:00.000Z',
            ['task-1'],
        ],
    ])('%s', async (_, status, activityAt, seenBefore, unreadAfter) => {
        // Only the clock is faked, so kea listeners and the activity debounce still run on real timers.
        jest.useFakeTimers({
            now: new Date('2026-09-30T12:00:00.000Z'),
            doNotFake: [
                'setTimeout',
                'clearTimeout',
                'setInterval',
                'clearInterval',
                'setImmediate',
                'queueMicrotask',
                'nextTick',
            ],
        })
        const markReadBodies: unknown[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/task_activity/': {
                    unread_count: 2,
                    results: [
                        {
                            id: 'row-1',
                            task_id: 'task-1',
                            channel_id: 'space-a',
                            activity_at: activityAt,
                            is_unread: true,
                        },
                        {
                            id: 'row-2',
                            task_id: 'task-2',
                            channel_id: 'space-b',
                            activity_at: activityAt,
                            is_unread: false,
                        },
                        {
                            id: 'row-3',
                            task_id: 'task-3',
                            channel_id: 'space-c',
                            activity_at: activityAt,
                            latest_comment_id: 'comment-1',
                            is_unread: true,
                        },
                    ],
                },
            },
            post: {
                '/api/projects/:team_id/task_activity/mark_read/': async ({ request }) => {
                    markReadBodies.push(await request.json())
                    return [status, { marked_read: 1, unread_count: 1 }]
                },
            },
        })
        try {
            const logic = spaceSceneLogic({ id: 'space-a' })
            logic.mount()
            await expectLogic(todaySpacesLogic).toDispatchActions(['loadTaskActivitySuccess'])
            expect([...todaySpacesLogic.values.unreadSessionIds]).toEqual(['task-1'])
            expect([...todaySpacesLogic.values.unreadSpaceIds]).toEqual(['space-a'])

            router.actions.push(urls.aiTask('task-1'))
            await expectLogic(todaySpacesLogic).toFinishAllListeners()

            expect(markReadBodies).toEqual([{ activities: [{ task_id: 'task-1', seen_before: seenBefore }] }])
            expect([...todaySpacesLogic.values.unreadSessionIds]).toEqual(unreadAfter)
            expect([...todaySpacesLogic.values.unreadSpaceIds]).toEqual(unreadAfter.length ? ['space-a'] : [])
        } finally {
            jest.useRealTimers()
        }
    })

    it('loads the members once the space turns private', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.members).toEqual([])

        logic.actions.setAccessConfirmOpen(true)
        logic.actions.updateSpace({ channel_type: 'private' })
        await expectLogic(logic).toDispatchActions(['spaceSaved', 'loadMembersSuccess'])

        expect(logic.values.members.map((member) => member.id)).toEqual([7])
        expect(logic.values.accessConfirmOpen).toBe(false)
    })

    it('stars a space from the sidebar menu and shows it on that space page', async () => {
        const logic = spaceSceneLogic({ id: 'space-b' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        todaySpacesLogic.actions.toggleStar('space-b', true)
        await expectLogic(todaySpacesLogic).toDispatchActions(['toggleStar', 'loadSpaces', 'loadSpacesSuccess'])

        expect(starRequests).toEqual([{ id: 'space-b', starred: true }])
        expect(todaySpacesLogic.values.pendingSpaceIds).toEqual([])
        expect(logic.values.space?.starred).toBe(true)
    })

    it('copies the project-scoped link to the space', async () => {
        const writeText = jest.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()

        todaySpacesLogic.actions.copySpaceLink('space-a')
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(todaySpacesLogic).toFinishAllListeners()

        expect(writeText).toHaveBeenCalledWith(
            expect.stringMatching(new RegExp(`^${window.location.origin}/project/\\d+/spaces/space-a$`))
        )
    })

    it('copies the canonical link a canvas carries, so it opens for people without the web canvas page', async () => {
        const writeText = jest.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()

        logic.actions.copyCanvasLink({ ...canvasesNamed(1)[0], url: 'https://app.example.com/code/canvas/space-a/c-0' })
        await expectLogic(logic).toFinishAllListeners()

        expect(writeText).toHaveBeenCalledWith('https://app.example.com/code/canvas/space-a/c-0')
    })

    it('fills this space’s composer with a suggestion without sending it', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        spaceSceneLogic({ id: 'space-b' }).mount()

        logic.actions.applySuggestion('Fix the flaky test')
        await expectLogic(logic).toFinishAllListeners()

        expect(composerSeedLogic({ panelId: spaceComposerPanelId('space-a') }).values.seed).toEqual({
            prompt: 'Fix the flaky test',
            autoSubmit: false,
        })
        expect(composerSeedLogic({ panelId: spaceComposerPanelId('space-b') }).values.seed).toBeNull()
        expect(logic.values.composerFocusRequest).toBe(1)
    })

    it.each([
        ['a preset', 14, null, 14],
        ['a custom value', 'custom', 45, 45],
        ['never', null, null, null],
    ] as [string, AutoArchiveSelection, number | null, number | null][])(
        'saves %s as the auto-archive days',
        async (_, selection, customDays, expected) => {
            const logic = spaceSceneLogic({ id: 'space-a' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setAutoArchiveSelection(selection)
            if (selection === 'custom') {
                logic.actions.setAutoArchiveCustomDays(customDays)
                logic.actions.saveAutoArchiveCustomDays()
            }
            await expectLogic(logic).toDispatchActions(['spaceSaved'])

            expect(spacePatches).toEqual([{ auto_archive_after_days: expected }])
            expect(logic.values.space?.auto_archive_after_days).toBe(expected)
        }
    )

    it.each([0, 366, 2.5, null])('never sends a custom auto-archive value of %s', async (days) => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setAutoArchiveSelection('custom')
        logic.actions.setAutoArchiveCustomDays(days)
        logic.actions.saveAutoArchiveCustomDays()
        await expectLogic(logic).toFinishAllListeners()

        expect(spacePatches).toEqual([])
        expect(logic.values.autoArchiveCustomSaveDisabledReason).not.toBeNull()
    })

    it('keeps the creator when the members picker drops them', async () => {
        const logic = spaceSceneLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setMemberIds([9])
        await expectLogic(logic).toDispatchActions(['setMemberIdsSuccess'])

        expect(memberUpdates).toEqual([[7, 9]])
        expect(logic.values.members.map((member) => member.id)).toEqual([7, 9])
    })
})
