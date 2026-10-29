import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

describe('supabaseAuthEmailsLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_supabase_auth_emails/settings/': {
                    supabase_url: '',
                    has_hook_secret: false,
                    hook_url: 'https://example.com/hook',
                    templates: {},
                    email_types: [],
                },
                '/api/projects/:team_id/messaging_templates/': { results: [], next: null },
            },
        })
        initKeaTests()
    })

    it.each([urls.workflows('channels'), urls.broadcasts('channels'), urls.transactional('channels')])(
        'opens the setup from a link to %s and drops the param on close',
        async (channelsUrl) => {
            router.actions.push(channelsUrl, { setup: 'supabase', other: 'kept' })
            const logic = supabaseAuthEmailsLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['openSetup']).toMatchValues({ isSetupOpen: true })

            logic.actions.closeSetup()

            expect(logic.values.isSetupOpen).toBe(false)
            expect(router.values.searchParams).toEqual({ other: 'kept' })

            logic.actions.openSetup()

            expect(router.values.searchParams).toEqual({ other: 'kept', setup: 'supabase' })
        }
    )
})
