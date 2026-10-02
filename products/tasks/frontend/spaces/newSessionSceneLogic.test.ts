import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { ChannelDTOApi } from '../generated/api.schemas'
import {
    NewSessionSpaceSource,
    newSessionComposerPanelId,
    newSessionSceneLogic,
    newSessionSpace,
} from './newSessionSceneLogic'

const space = (id: string, systemRole: ChannelDTOApi['system_role'] = null): ChannelDTOApi =>
    ({ id, name: id, system_role: systemRole, repositories: [] }) as unknown as ChannelDTOApi

const SPACES = [space('general', 'general'), space('me', 'personal'), space('checkout')]

describe('newSessionSceneLogic', () => {
    describe('newSessionSpace', () => {
        it.each<[string, string | null, string | null, string, NewSessionSpaceSource]>([
            ['a space’s own New session wins over the last space', 'checkout', 'general', 'checkout', 'route'],
            ['a generic New session uses the last space', null, 'checkout', 'checkout', 'last_used'],
            ['a generic New session with no last space uses personal', null, null, 'me', 'personal'],
            ['a deleted last space falls back to personal', null, 'gone', 'me', 'personal'],
            ['a deleted route space falls back to the last space', 'gone', 'checkout', 'checkout', 'last_used'],
        ])('%s', (_, routeSpaceId, lastSpaceId, expectedId, expectedSource) => {
            const { space: chosen, source } = newSessionSpace(SPACES, routeSpaceId, lastSpaceId)
            expect({ id: chosen?.id, source }).toEqual({ id: expectedId, source: expectedSource })
        })
    })

    describe('a question from the URL', () => {
        beforeEach(() => {
            localStorage.clear()
            useMocks({
                get: {
                    '/api/projects/:team_id/task_channels/': () => [200, SPACES],
                    '/api/projects/:team_id/tasks/': () => [200, { results: [], count: 0 }],
                },
            })
            initKeaTests()
        })

        it.each([
            ['sends it once the organization accepts AI data processing', true],
            ['only fills the composer without that consent', false],
        ])('%s', async (_, approved) => {
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: approved,
            })
            router.actions.push(urls.taskNewSession(), { ask: 'Walk me through my briefing' })
            const logic = newSessionSceneLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(composerSeedLogic({ panelId: newSessionComposerPanelId('me') }).values.seed).toEqual({
                prompt: 'Walk me through my briefing',
                autoSubmit: approved,
            })
            expect(router.values.searchParams).toEqual({})
            logic.unmount()
        })
    })
})
