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
        ['?tab=rankings', { tab: 'rankings' }, undefined, 'rankings'],
        ['?tab=settings', { tab: 'settings' }, undefined, 'settings'],
        ['?tab=Rankings', { tab: 'Rankings' }, undefined, 'rankings'],
        ['#tab:Rankings', undefined, '#tab:Rankings', 'rankings'],
        ['?tab=not-a-tab', { tab: 'not-a-tab' }, undefined, 'overview'],
    ])('opens the tab a link names (%s)', async (_link, search, hash, expected) => {
        router.actions.push(urls.webAnalyticsContentAutopilot(), search, hash)
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
