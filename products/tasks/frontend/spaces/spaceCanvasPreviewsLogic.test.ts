import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import {
    SPACE_CANVAS_PREVIEWS_MAX_LOADING,
    spaceCanvasPreviewKey,
    spaceCanvasPreviewsLogic,
} from './spaceCanvasPreviewsLogic'

type ViewMock = [number, Record<string, unknown>]

const readyView = (id: string): ViewMock => [
    200,
    { published_build: { build_status: 'ready', artifact_url: `https://artifacts.example.com/${id}/index.html` } },
]

describe('spaceCanvasPreviewsLogic', () => {
    let logic: ReturnType<typeof spaceCanvasPreviewsLogic.build>
    let viewRequests: string[]
    let respond: (id: string) => ViewMock
    let release: () => void
    let gate: Promise<void>

    beforeEach(() => {
        viewRequests = []
        respond = readyView
        gate = Promise.resolve()
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': async ({ params }) => {
                    const id = String(params.id)
                    viewRequests.push(id)
                    await gate
                    return respond(id)
                },
            },
        })
        initKeaTests()
        logic = spaceCanvasPreviewsLogic({ spaceId: 'space-a' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads at most a few previews at once and starts queued ones as others settle', async () => {
        gate = new Promise((resolve) => {
            release = resolve
        })
        const ids = ['c1', 'c2', 'c3', 'c4', 'c5']
        for (const id of ids) {
            logic.actions.requestPreview(`${id}:build`, id)
        }

        await expectLogic(logic).delay(0)
        expect(viewRequests).toHaveLength(SPACE_CANVAS_PREVIEWS_MAX_LOADING)
        expect(logic.values.previews['c5:build'].status).toEqual('queued')

        release()
        await expectLogic(logic).toFinishAllListeners()
        expect(viewRequests.sort()).toEqual(ids)
        expect(logic.values.previews['c5:build']).toEqual({
            canvasId: 'c5',
            status: 'ready',
            artifactUrl: 'https://artifacts.example.com/c5/index.html',
        })
    })

    it.each([
        [
            'the build is not ready',
            (): ViewMock => [200, { published_build: { build_status: 'building', artifact_url: null } }],
        ],
        [
            'artifact delivery is unavailable',
            (): ViewMock => [200, { published_build: { build_status: 'ready', artifact_url: null } }],
        ],
        ['the view request fails', (): ViewMock => [500, { detail: 'error' }]],
    ])('falls back to no preview when %s', async (_, response) => {
        respond = response
        logic.actions.requestPreview('c1:build', 'c1')

        await expectLogic(logic).toDispatchActions(['previewSettled'])
        expect(logic.values.previews['c1:build']).toEqual({ canvasId: 'c1', status: 'unavailable', artifactUrl: null })
    })

    it.each([
        ['a canvas with no published build', { kind: 'freeform', published_build_id: null }, null],
        ['a grid canvas', { kind: 'grid', published_build_id: 'b1' }, null],
        ['a built freeform canvas', { kind: 'freeform', published_build_id: 'b1' }, 'c1:b1'],
    ])('keys %s for preview', (_, fields, expected) => {
        expect(spaceCanvasPreviewKey({ id: 'c1', ...fields } as CanvasApi)).toEqual(expected)
    })
})
