import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayCommentsLogic } from './replayCommentsLogic'

const comment = (id: string, overrides: Record<string, any> = {}): Record<string, any> => ({
    id,
    content: `comment ${id}`,
    rich_content: null,
    version: 0,
    created_at: '2024-05-01T10:00:00Z',
    created_by: null,
    scope: 'Replay',
    item_id: 'the-recording-id',
    item_context: { time_in_recording: '2024-05-01T09:00:12Z', milliseconds_into_recording: 72000 },
    is_task: false,
    completed_at: null,
    completed_by: null,
    slack_thread: null,
    ...overrides,
})

describe('replayCommentsLogic', () => {
    let logic: ReturnType<typeof replayCommentsLogic.build>
    let requestedUrls: string[]
    let responseStatus: number

    beforeEach(() => {
        requestedUrls = []
        responseStatus = 200
        useMocks({
            get: {
                '/api/projects/:team_id/comments/': ({ request }) => {
                    requestedUrls.push(request.url)
                    if (responseStatus !== 200) {
                        return [responseStatus, { detail: 'nope' }]
                    }
                    const cursor = new URL(request.url).searchParams.get('cursor')
                    if (cursor === 'page-2') {
                        return [200, { next: null, previous: null, results: [comment('2')] }]
                    }
                    return [
                        200,
                        {
                            next: 'http://localhost/api/projects/997/comments/?cursor=page-2',
                            previous: null,
                            results: [comment('1')],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = replayCommentsLogic()
    })

    // The whole point of the tab: dropping either filter would show every team member's
    // comments from every product, not the person's own replay comments.
    it("asks only for the current user's replay comments", async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const params = new URL(requestedUrls[0]).searchParams
        expect(params.get('scope')).toEqual('Replay')
        expect(params.get('created_by')).toEqual(String(userLogic.values.user?.id))
    })

    it('links each comment to its moment in the recording', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.commentRows).toMatchObject([
            {
                id: '1',
                text: 'comment 1',
                timeInRecording: '01:12',
                recordingUrl: expect.stringContaining('/replay/the-recording-id?timestamp='),
            },
        ])
    })

    it('appends the next page instead of replacing the loaded one', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.hasMoreComments).toBe(true)

        logic.actions.loadMoreReplayComments()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.commentRows.map((row) => row.id)).toEqual(['1', '2'])
        expect(logic.values.hasMoreComments).toBe(false)
        expect(new URL(requestedUrls[1]).searchParams.get('cursor')).toEqual('page-2')
    })

    // A failed load leaves no rows, so without this flag the tab would tell the person
    // they have never commented.
    it('reports a failed load instead of reading as an empty list', async () => {
        responseStatus = 500
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasLoadError).toBe(true)
        expect(logic.values.firstPageLoading).toBe(false)
    })
})
