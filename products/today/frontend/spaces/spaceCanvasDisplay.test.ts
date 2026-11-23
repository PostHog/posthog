import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { spaceCanvasSections } from './spaceCanvasDisplay'

describe('spaceCanvasSections', () => {
    const canvas = (id: string, pinnedAt: string | null = null): CanvasApi =>
        ({ id, pinned: pinnedAt !== null, pinned_at: pinnedAt }) as CanvasApi

    it.each<[string, CanvasApi[], string[], string[]]>([
        ['nothing is pinned', [canvas('a'), canvas('b')], [], ['a', 'b']],
        [
            'canvases are pinned',
            [
                canvas('a'),
                canvas('old-pin', '2026-09-01T10:00:00Z'),
                canvas('b'),
                canvas('new-pin', '2026-09-20T10:00:00Z'),
            ],
            ['new-pin', 'old-pin'],
            ['a', 'b'],
        ],
        ['every canvas is pinned', [canvas('a', '2026-09-01T10:00:00Z')], ['a'], []],
    ])('lists the newest pins first and keeps the rest in order when %s', (_, canvases, pinned, rest) => {
        const sections = spaceCanvasSections(canvases)

        expect(sections.pinned.map((item) => item.id)).toEqual(pinned)
        expect(sections.rest.map((item) => item.id)).toEqual(rest)
    })
})
