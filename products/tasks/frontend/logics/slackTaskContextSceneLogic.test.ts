import { MOCK_TEAM_ID } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'

import { SlackThreadContextResponseApi } from '../generated/api.schemas'
import { slackTaskContextSceneLogic } from './slackTaskContextSceneLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksSlackThreadContextRetrieve: jest.fn(),
}))

// eslint-disable-next-line @typescript-eslint/no-var-requires
const generatedApi = require('products/tasks/frontend/generated/api')

const mockResponse: SlackThreadContextResponseApi = {
    thread: {
        url: 'https://posthog.slack.com/archives/C0/p1779956938619299',
        channel: 'C0',
        thread_ts: '1779956938.619299',
        slack_workspace_id: 'T_SLACK',
        mentioning_slack_user_id: 'U_ANDY',
    },
    task: {
        id: 'task-1',
        team_id: 2,
        title: 'Investigate flaky test',
        repository: null,
        origin_product: 'slack',
        created_at: '2026-05-28T08:30:00Z',
        url: 'http://testserver/project/2/tasks/task-1',
    },
    runs: [],
}

describe('slackTaskContextSceneLogic', () => {
    let logic: ReturnType<typeof slackTaskContextSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = slackTaskContextSceneLogic()
        logic.mount()
        ;(generatedApi.tasksSlackThreadContextRetrieve as jest.Mock).mockReset()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('refuses to submit when url is empty', async () => {
        await logic.asyncActions.loadResult()
        expect(generatedApi.tasksSlackThreadContextRetrieve).not.toHaveBeenCalled()
        expect(logic.values.submissionError?.detail).toBe('Enter a Slack thread URL.')
        expect(logic.values.result).toBeNull()
    })

    it('loads a result when the API call succeeds', async () => {
        ;(generatedApi.tasksSlackThreadContextRetrieve as jest.Mock).mockResolvedValueOnce(mockResponse)
        logic.actions.setUrl('https://posthog.slack.com/archives/C0/p1779956938619299')

        await logic.asyncActions.loadResult()

        expect(generatedApi.tasksSlackThreadContextRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            url: 'https://posthog.slack.com/archives/C0/p1779956938619299',
        })
        expect(logic.values.result).toEqual(mockResponse)
        expect(logic.values.submissionError).toBeNull()
    })

    it('surfaces a 403 error from the backend', async () => {
        ;(generatedApi.tasksSlackThreadContextRetrieve as jest.Mock).mockRejectedValueOnce({
            status: 403,
            data: { detail: 'Forbidden' },
        })
        logic.actions.setUrl('https://posthog.slack.com/archives/C0/p1779956938619299')

        await logic.asyncActions.loadResult()

        expect(logic.values.result).toBeNull()
        expect(logic.values.submissionError).toEqual({ status: 403, detail: 'Forbidden' })
    })

    it('surfaces a 404 error from the backend', async () => {
        ;(generatedApi.tasksSlackThreadContextRetrieve as jest.Mock).mockRejectedValueOnce({
            status: 404,
            data: { detail: 'no_mapping' },
        })
        logic.actions.setUrl('https://posthog.slack.com/archives/C0/p1779956938619299')

        await logic.asyncActions.loadResult()

        expect(logic.values.submissionError).toEqual({ status: 404, detail: 'no_mapping' })
    })

    it('clears state on clearResult', async () => {
        ;(generatedApi.tasksSlackThreadContextRetrieve as jest.Mock).mockResolvedValueOnce(mockResponse)
        logic.actions.setUrl('https://posthog.slack.com/archives/C0/p1779956938619299')
        await logic.asyncActions.loadResult()
        expect(logic.values.result).toEqual(mockResponse)

        logic.actions.clearResult()
        expect(logic.values.url).toBe('')
        expect(logic.values.result).toBeNull()
        expect(logic.values.submissionError).toBeNull()
    })
})
