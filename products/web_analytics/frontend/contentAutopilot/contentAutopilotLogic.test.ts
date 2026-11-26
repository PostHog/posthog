import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { contentAutopilotLogic } from './contentAutopilotLogic'

describe('contentAutopilotLogic', () => {
    let logic: ReturnType<typeof contentAutopilotLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = contentAutopilotLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it.each([
        ['rankings', 'rankings'],
        ['settings', 'settings'],
        ['not-a-tab', 'overview'],
    ])('opens the tab a link names (%s)', async (param, expected) => {
        router.actions.push(urls.webAnalyticsContentAutopilot(), { tab: param })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.workspaceTab).toBe(expected)
    })

    it('writes the open tab to the URL and keeps the filters next to it', async () => {
        router.actions.push(urls.webAnalyticsContentAutopilot(), { engine: 'claude-web-search' })

        logic.actions.setWorkspaceTab('keywords')
        expect(router.values.searchParams).toEqual({ engine: 'claude-web-search', tab: 'keywords' })

        logic.actions.setWorkspaceTab('overview')
        expect(router.values.searchParams).toEqual({ engine: 'claude-web-search' })
    })
})
