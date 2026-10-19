import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_SPACE_FEED_FILTERS } from './spaceFeedEntries'
import { spaceFeedSelectionLogic } from './spaceFeedSelectionLogic'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'
import { spaceSceneLogic } from './spaceSceneLogic'

const escapeHandledByMenu = (): void => {
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    event.preventDefault()
    window.dispatchEvent(event)
}

const escapeFromOpenMenu = (): void => {
    const menu = document.createElement('div')
    menu.setAttribute('role', 'menu')
    menu.setAttribute('data-open', '')
    document.body.append(menu)
    menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    menu.remove()
}

describe('spaceFeedSelectionLogic', () => {
    let logic: ReturnType<typeof spaceFeedSelectionLogic.build>
    let archivedIds: string[]

    beforeEach(async () => {
        archivedIds = []
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_channels/:id/': ({ params }) => [200, { id: params.id, name: 'Space' }],
                '/api/projects/:team_id/task_activity/': { results: [] },
                '/api/projects/:team_id/canvases/': { results: [], count: 0 },
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const channel = new URL(request.url).searchParams.get('channel')
                    const results = ['task-1', 'task-2', 'task-3'].map((id, index) => ({
                        id,
                        title: id,
                        channel,
                        archived: archivedIds.includes(id),
                        last_activity_at: `2026-09-2${8 - index}T12:00:00Z`,
                        latest_run: null,
                    }))
                    return [200, { results: channel ? results : [], count: channel ? results.length : 0 }]
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ params, request }) => {
                    if (((await request.json()) as { archived?: boolean }).archived) {
                        archivedIds.push(String(params.id))
                    }
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        logic = spaceFeedSelectionLogic({ id: 'space-a' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    it('selects a Shift-click range in feed order from the last toggled session', () => {
        expect(logic.values.orderedSessionIds).toEqual(['task-1', 'task-2', 'task-3'])

        logic.actions.toggleSessionSelection('task-3')
        logic.actions.selectSessionRange('task-1')

        expect(logic.values.selectedSessionIds).toEqual(['task-3', 'task-1', 'task-2'])
        expect(logic.values.selectAll).toBe('all')
    })

    it('archives the selection and drops it from the feed', async () => {
        logic.actions.setSelection({ ids: ['task-1', 'task-2'], anchorId: 'task-2' })
        logic.actions.requestBulkArchive()
        await expectLogic(logic).toDispatchActions(['bulkActionFinished'])
        await expectLogic(spaceSceneLogic({ id: 'space-a' })).toDispatchActions(['loadSessionsSuccess'])

        expect(archivedIds.sort()).toEqual(['task-1', 'task-2'])
        expect(logic.values.orderedSessionIds).toEqual(['task-3'])
        expect(logic.values.selectedSessionIds).toEqual([])
    })

    it.each([
        ['the view changes', () => spaceFeedViewLogic.actions.setView('list')],
        ['the types change', () => spaceFeedViewLogic.actions.setTypes(['task'])],
        [
            'the filters change',
            () => spaceFeedViewLogic.actions.setFilters({ ...DEFAULT_SPACE_FEED_FILTERS, pinned: 'pinned' }),
        ],
        ['Escape is pressed', () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
    ])('clears the selection when %s', (_, clear) => {
        logic.actions.setSelection({ ids: ['task-1', 'task-2'], anchorId: 'task-2' })
        clear()

        expect(logic.values.selection.ids).toEqual([])
    })

    it.each([
        ['a menu already handled it', () => escapeHandledByMenu()],
        ['it comes from inside an open menu', () => escapeFromOpenMenu()],
    ])('keeps the selection on the first Escape when %s, and clears it on the next', (_, closeMenu) => {
        logic.actions.setSelection({ ids: ['task-1', 'task-2'], anchorId: 'task-2' })
        closeMenu()

        expect(logic.values.selection.ids).toEqual(['task-1', 'task-2'])

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

        expect(logic.values.selection.ids).toEqual([])
    })
})
