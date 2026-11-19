import { act, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    MessageTemplateApi,
    PatchedSupabaseAuthEmailSettingsUpdateApi,
    SupabaseAuthEmailSettingsApi,
    SupabaseEmailTypeApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { supabaseAuthEmailsLogic } from './supabaseAuthEmailsLogic'

const SENDABLE = '00000000-0000-4000-8000-000000000001'
const NOT_SENSITIVE = '00000000-0000-4000-8000-000000000002'
const DELETED = '00000000-0000-4000-8000-000000000003'
const NOT_TRANSACTIONAL = '00000000-0000-4000-8000-000000000004'
const EMAIL_TYPES: SupabaseEmailTypeApi[] = [
    { value: 'signup', label: 'Confirm sign-up', has_starter_template: true },
    { value: 'recovery', label: 'Reset password', has_starter_template: true },
    { value: 'invite', label: 'Invite user', has_starter_template: false },
]

type FailingAction = 'saveConnection' | 'disconnect' | 'createStarterTemplates'

describe('supabaseAuthEmailsLogic', () => {
    let stored: Pick<SupabaseAuthEmailSettingsApi, 'supabase_url' | 'has_hook_secret' | 'templates'>
    let messageTemplates: Pick<MessageTemplateApi, 'id' | 'transactional_hog_flow_id' | 'sensitive' | 'deleted'>[]
    let patches: PatchedSupabaseAuthEmailSettingsUpdateApi[]
    let failure: [number, Record<string, string>?] | null
    let failedLoads: ('settings' | 'templates')[]
    let templatesListed: Promise<void>

    const settingsResponse = (): SupabaseAuthEmailSettingsApi => ({
        ...stored,
        hook_url: 'https://example.com/hook',
        email_types: EMAIL_TYPES,
    })

    beforeEach(() => {
        stored = { supabase_url: '', has_hook_secret: false, templates: {} }
        messageTemplates = [
            { id: SENDABLE, transactional_hog_flow_id: 'flow-1', sensitive: true, deleted: false },
            { id: NOT_SENSITIVE, transactional_hog_flow_id: 'flow-2', sensitive: false, deleted: false },
            { id: DELETED, transactional_hog_flow_id: 'flow-3', sensitive: true, deleted: true },
            { id: NOT_TRANSACTIONAL, transactional_hog_flow_id: null, sensitive: true, deleted: false },
        ]
        patches = []
        failure = null
        failedLoads = []
        templatesListed = Promise.resolve()
        const sendable = (id: string): boolean =>
            messageTemplates.some((t) => t.id === id && t.transactional_hog_flow_id && t.sensitive && !t.deleted)
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_supabase_auth_emails/settings/': () =>
                    failedLoads.includes('settings') ? [500] : [200, settingsResponse()],
                '/api/projects/:team_id/messaging_templates/': async ({ request }) => {
                    await templatesListed
                    const params = new URL(request.url).searchParams
                    const offset = Number(params.get('offset') ?? 0)
                    const limit = Math.min(Number(params.get('limit') ?? 100), 100)
                    return failedLoads.includes('templates')
                        ? [500]
                        : [
                              200,
                              {
                                  count: messageTemplates.length,
                                  results: messageTemplates.slice(offset, offset + limit),
                              },
                          ]
                },
            },
            patch: {
                '/api/projects/:team_id/messaging_supabase_auth_emails/settings/': async ({ request }) => {
                    if (failure) {
                        return failure
                    }
                    const body = (await request.json()) as PatchedSupabaseAuthEmailSettingsUpdateApi
                    patches.push(body)
                    if (body.supabase_url !== undefined) {
                        stored.supabase_url = body.supabase_url
                    }
                    stored.has_hook_secret = stored.has_hook_secret || !!body.hook_secret
                    stored.templates = body.templates ?? stored.templates
                    return [200, settingsResponse()]
                },
            },
            delete: {
                '/api/projects/:team_id/messaging_supabase_auth_emails/settings/': () => {
                    if (failure) {
                        return failure
                    }
                    stored = { supabase_url: '', has_hook_secret: false, templates: {} }
                    return [200, settingsResponse()]
                },
            },
            post: {
                '/api/projects/:team_id/messaging_supabase_auth_emails/starter_templates/': () => {
                    if (failure) {
                        return failure
                    }
                    const starters = EMAIL_TYPES.filter((type) => type.has_starter_template).map((type) => type.value)
                    for (const type of starters.filter((type) => !sendable(stored.templates[type]))) {
                        const id = `00000000-0000-4000-9000-00000000000${messageTemplates.length}`
                        messageTemplates.push({ id, transactional_hog_flow_id: id, sensitive: true, deleted: false })
                        stored.templates = { ...stored.templates, [type]: id }
                    }
                    return [200, settingsResponse()]
                },
            },
        })
        initKeaTests()
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
    })

    const settled = async (logic: ReturnType<typeof supabaseAuthEmailsLogic.build>): Promise<void> => {
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
        })
    }

    const mounted = async (): Promise<ReturnType<typeof supabaseAuthEmailsLogic.build>> => {
        const logic = supabaseAuthEmailsLogic()
        logic.mount()
        await settled(logic)
        return logic
    }

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

            router.actions.push(channelsUrl, { other: 'kept' })

            expect(logic.values.isSetupOpen).toBe(false)
        }
    )

    it.each([
        [{ supabase_url: '', has_hook_secret: false, templates: {} }, 'not-set-up'],
        [{ supabase_url: 'https://a.supabase.co', has_hook_secret: false, templates: {} }, 'incomplete'],
        [{ supabase_url: '', has_hook_secret: true, templates: {} }, 'incomplete'],
        [{ supabase_url: '', has_hook_secret: false, templates: { signup: SENDABLE } }, 'incomplete'],
        [{ supabase_url: 'https://a.supabase.co', has_hook_secret: true, templates: {} }, 'connected'],
    ])('shows %j as %s', async (saved, status) => {
        stored = saved
        const logic = supabaseAuthEmailsLogic()
        logic.mount()
        expect(logic.values.status).toBeNull()
        await settled(logic)
        expect(logic.values.status).toEqual(status)
    })

    it.each(['settings', 'templates'] as const)('shows a failed %s load and only that one', async (failed) => {
        failedLoads = [failed]
        const logic = await mounted()
        logic.actions.openSetup()
        await settled(logic)
        expect(logic.values).toMatchObject({
            settingsLoadFailed: failed === 'settings',
            templatesLoadFailed: failed === 'templates',
        })
    })

    it('clears a failed template load once "Try again" succeeds', async () => {
        failedLoads = ['templates']
        const logic = await mounted()
        logic.actions.openSetup()
        await settled(logic)
        failedLoads = []
        logic.actions.loadTemplates()
        await settled(logic)
        expect(logic.values.templatesLoadFailed).toBe(false)
        expect(logic.values.transactionalTemplates?.map((template) => template.id)).toEqual([SENDABLE])
    })

    it.each([
        [
            '  v1,whsec_abc  ',
            { supabase_url: 'https://a.supabase.co', hook_secret: 'v1,whsec_abc' },
            { status: 'connected', hookSecret: '' },
        ],
        ['   ', { supabase_url: 'https://a.supabase.co' }, { status: 'incomplete' }],
    ])('saves the trimmed URL with secret %j', async (secret, patch, after) => {
        const logic = await mounted()
        logic.actions.openSetup()
        logic.actions.setSupabaseUrl(' https://a.supabase.co ')
        logic.actions.setHookSecret(secret)
        expect(logic.values.connectionChanged).toBe(true)

        logic.actions.saveConnection()
        await settled(logic)

        expect(patches).toEqual([patch])
        expect(logic.values).toMatchObject({ ...after, connectionChanged: false })
    })

    it('maps and unmaps a template without dropping a connection still being typed', async () => {
        stored.templates = { recovery: SENDABLE }
        const logic = await mounted()
        logic.actions.openSetup()
        logic.actions.setSupabaseUrl('https://draft.supabase.co')
        logic.actions.setHookSecret('v1,whsec_draft')

        logic.actions.setTemplate('signup', SENDABLE)
        await settled(logic)
        logic.actions.setTemplate('recovery', null)
        await settled(logic)

        expect(patches).toEqual([
            { templates: { recovery: SENDABLE, signup: SENDABLE } },
            { templates: { signup: SENDABLE } },
        ])
        expect(logic.values).toMatchObject({ supabaseUrl: 'https://draft.supabase.co', hookSecret: 'v1,whsec_draft' })
    })

    it.each([
        ['https://a.supabase.co ', '', false],
        ['https://a.supabase.co', '  ', false],
        ['https://a.supabase.co', 'v1,whsec_new', true],
        ['https://b.supabase.co', '', true],
    ])('counts URL %j with secret %j as a change: %s', async (url, secret, changed) => {
        stored.supabase_url = 'https://a.supabase.co'
        const logic = await mounted()
        logic.actions.setSupabaseUrl(url)
        logic.actions.setHookSecret(secret)
        expect(logic.values.connectionChanged).toBe(changed)
    })

    it('starts each open from the saved URL with no secret', async () => {
        stored.supabase_url = 'https://a.supabase.co'
        const logic = await mounted()
        logic.actions.openSetup()
        logic.actions.setSupabaseUrl('https://draft.supabase.co')
        logic.actions.setHookSecret('v1,whsec_draft')
        logic.actions.closeSetup()

        logic.actions.openSetup()

        expect(logic.values).toMatchObject({
            supabaseUrl: 'https://a.supabase.co',
            hookSecret: '',
            connectionChanged: false,
        })
    })

    it('disconnects, clears the form and closes the setup', async () => {
        stored = { supabase_url: 'https://a.supabase.co', has_hook_secret: true, templates: { signup: SENDABLE } }
        const logic = await mounted()
        logic.actions.openSetup()
        logic.actions.setHookSecret('v1,whsec_draft')

        logic.actions.disconnect()
        await settled(logic)

        expect(await screen.findByText('Disconnected your Supabase project')).toBeTruthy()
        expect(logic.values).toMatchObject({
            status: 'not-set-up',
            isSetupOpen: false,
            supabaseUrl: '',
            hookSecret: '',
        })
    })

    it.each([SENDABLE, NOT_SENSITIVE, DELETED, NOT_TRANSACTIONAL])(
        'lists the sign-up email as missing a template only when mapped to an unusable one (%s)',
        async (mapped) => {
            stored.templates = { signup: mapped, recovery: SENDABLE }
            const logic = await mounted()
            expect(logic.values.missingStarterTypes).toBeNull()

            logic.actions.openSetup()
            await settled(logic)

            expect(logic.values.missingStarterTypes?.map((type) => type.value)).toEqual(
                mapped === SENDABLE ? [] : ['signup']
            )
        }
    )

    it('counts a mapped template that arrives past the first page of 100 as usable', async () => {
        const filler = Array.from({ length: 100 }, (_, index) => ({
            id: `00000000-0000-4000-a000-${String(index).padStart(12, '0')}`,
            transactional_hog_flow_id: null,
            sensitive: true,
            deleted: false,
        }))
        messageTemplates = [...filler, ...messageTemplates]
        stored.templates = { signup: SENDABLE, recovery: SENDABLE }
        const logic = await mounted()

        logic.actions.openSetup()
        await settled(logic)

        expect(logic.values.transactionalTemplates?.map((template) => template.id)).toEqual([SENDABLE])
        expect(logic.values.missingStarterTypes).toEqual([])
    })

    it.each([
        [{}, 'Created 2 starter templates', null],
        [{ signup: SENDABLE, recovery: DELETED }, 'Created 1 starter template', null],
        [{ signup: SENDABLE, recovery: SENDABLE }, 'Every email already has a template, so nothing was created', []],
    ])('creates starter templates over mapping %j and says %s', async (mapping, message, missingWhileReloading) => {
        stored.templates = mapping
        const logic = await mounted()
        logic.actions.openSetup()
        await settled(logic)

        let listTemplates = (): void => {}
        templatesListed = new Promise((resolve) => (listTemplates = resolve))

        logic.actions.createStarterTemplates()

        expect(await screen.findByText(message)).toBeTruthy()
        expect(logic.values.missingStarterTypes).toEqual(missingWhileReloading)
        listTemplates()
        await settled(logic)
        expect(logic.values.missingStarterTypes).toEqual([])
    })

    it.each<[FailingAction, [number, Record<string, string>?], string]>([
        ['saveConnection', [500], "Couldn't save the Supabase settings. Try again."],
        ['disconnect', [500], "Couldn't disconnect your Supabase project. Try again."],
        ['createStarterTemplates', [500], "Couldn't create the starter templates. Try again."],
        ['createStarterTemplates', [400, { detail: 'Verify an email sender first.' }], 'Verify an email sender first.'],
    ])('shows why %s failed (%j)', async (action, response, message) => {
        stored = { supabase_url: 'https://a.supabase.co', has_hook_secret: true, templates: {} }
        const logic = await mounted()
        failure = response

        logic.actions[action]()
        await settled(logic)

        expect(await screen.findByText(message)).toBeTruthy()
        expect(logic.values.status).toEqual('connected')
    })
})
