import { TodaySessionSelection } from '~/layout/today/todaySessionSelection'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { SpaceFeedSection } from './spaceFeedEntries'
import { spaceFeedSessions, toggleAllSelection } from './spaceFeedSelection'

function item(id: string): TodayWorkItem {
    return { id, kind: 'session' } as TodayWorkItem
}

describe('spaceFeedSelection', () => {
    it('lists only session rows, in feed order across sections', () => {
        const sections: SpaceFeedSection[] = [
            {
                key: 'today',
                label: 'Today',
                entries: [
                    { kind: 'task', key: 't2', item: item('t2') },
                    {
                        kind: 'pr',
                        key: 'pr:1',
                        item: item('t2'),
                        pullRequest: { url: 'https://github.com/acme/web/pull/1', number: 1, repository: 'acme/web' },
                    },
                    { kind: 'canvas', key: 'canvas:c1', canvas: { id: 'c1' } as CanvasApi },
                ],
            },
            { key: 'older', label: 'Older', entries: [{ kind: 'task', key: 't1', item: item('t1') }] },
        ]

        expect(spaceFeedSessions(sections).map((session) => session.id)).toEqual(['t2', 't1'])
    })

    it.each<[string, string[], TodaySessionSelection]>([
        ['selects every session from a partial pick', ['t2'], { ids: ['t1', 't2', 't3'], anchorId: null }],
        ['clears a full pick', ['t3', 't1', 't2'], { ids: [], anchorId: null }],
    ])('select all %s', (_, selected, expected) => {
        expect(toggleAllSelection(selected, ['t1', 't2', 't3'])).toEqual(expected)
    })
})
