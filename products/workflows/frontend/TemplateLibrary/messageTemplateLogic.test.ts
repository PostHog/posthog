import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { messageTemplateLogic } from './messageTemplateLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockToast = require('lib/lemon-ui/LemonToast').lemonToast

describe('messageTemplateLogic', () => {
    let logic: ReturnType<typeof messageTemplateLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': { id: 'existing-id', name: 'Existing' },
                '/api/environments/:team_id/hog_functions/:id/': { id: 'message-id', name: 'Sent message' },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('unsaved-changes guard', () => {
        let confirmSpy: jest.SpyInstance

        beforeEach(() => {
            // window.confirm is the boundary kea-router calls to block in-app navigation.
            confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()
        })

        afterEach(() => {
            confirmSpy.mockRestore()
        })

        it.each([
            { description: 'blocks navigation away from an unsaved new template', changed: true, expectedCalls: 1 },
            {
                description: 'does not block navigation when there are no unsaved changes',
                changed: false,
                expectedCalls: 0,
            },
        ])('$description', async ({ changed, expectedCalls }) => {
            if (changed) {
                logic.actions.setTemplateValue('name', 'My one-hour template')
                await expectLogic(logic).toMatchValues({ templateChanged: true })
            } else {
                await expectLogic(logic).toMatchValues({ templateChanged: false })
            }

            router.actions.push('/workflows/library')

            expect(confirmSpy).toHaveBeenCalledTimes(expectedCalls)
        })
    })

    describe('submit validation feedback', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            { missing: 'name', key: 'name', toast: 'Name is required' },
            { missing: 'subject', key: 'content.email.subject', toast: 'Subject is required' },
        ])('toasts when the $missing is missing', async ({ key, toast }) => {
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()

            logic.actions.setTemplateValue(key, '')
            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            }).toDispatchActions(['submitTemplateFailure'])

            expect(mockToast.error).toHaveBeenCalledWith(toast)
        })
    })

    describe('save failure feedback', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            {
                description: '404 tells the user the template is gone from this environment',
                status: 404,
                toast: 'This template no longer exists in this environment. It may have been deleted.',
                withButton: true,
            },
            {
                description: 'other failures fall back to a generic retry message',
                status: 500,
                toast: 'Failed to save template. Please try again.',
                withButton: false,
            },
        ])('$description', async ({ status, toast, withButton }) => {
            useMocks({
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [status, { detail: 'nope' }],
                },
            })

            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.saveTemplate({ id: 'existing-id', name: 'Existing' })
            }).toDispatchActions(['saveTemplateFailure'])

            if (withButton) {
                expect(mockToast.error).toHaveBeenCalledWith(
                    toast,
                    expect.objectContaining({ button: expect.anything() })
                )
            } else {
                expect(mockToast.error).toHaveBeenCalledWith(toast)
            }
        })
    })

    describe('edited elsewhere', () => {
        const LOADED_AT = '2026-01-01T00:00:00Z'
        const LATER = '2026-01-01T00:01:00Z'
        let serverTemplate: { id: string; name: string; updated_at: string }

        const edited = (overrides: Partial<ResourceEditedEvent> = {}): ResourceEditedEvent => ({
            notification_type: 'resource_edited',
            team_id: 1,
            resource_type: 'MessageTemplate',
            resource_id: 'existing-id',
            updated_at: LATER,
            actor_user_id: null,
            ...overrides,
        })

        beforeEach(async () => {
            serverTemplate = { id: 'existing-id', name: 'Existing', updated_at: LOADED_AT }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [200, serverTemplate],
                },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [
                        200,
                        { ...serverTemplate, name: 'Saved here', updated_at: LATER },
                    ],
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
            // From here a reload shows as this name on the form.
            serverTemplate = { ...serverTemplate, name: 'Renamed by the agent', updated_at: LATER }
        })

        // A clean form takes the server copy at once. Unsaved edits get the banner instead of a silent replacement.
        it.each([
            { description: 'reloads a clean form', dirty: false, reloads: true },
            { description: 'warns instead of replacing unsaved edits', dirty: true, reloads: false },
        ])('$description', async ({ dirty, reloads }) => {
            if (dirty) {
                logic.actions.setTemplateValue('name', 'My edit')
            }

            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                externallyEdited: !reloads,
                isSyncingExternalEdit: false,
                templateChanged: dirty,
            })
            expect(logic.values.template.name).toBe(reloads ? 'Renamed by the agent' : 'My edit')
        })

        it.each([
            { description: 'its own save echo', event: edited({ updated_at: LOADED_AT }) },
            { description: 'another template', event: edited({ resource_id: 'other-id' }) },
            { description: 'another resource type', event: edited({ resource_type: 'HogFlow' }) },
        ])('ignores $description', async ({ event }) => {
            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(event)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: false, isSyncingExternalEdit: false })
            expect(logic.values.template.name).toBe('Existing')
        })

        // The realtime echo of our own save can beat its HTTP response, while the loaded stamp is still the old one.
        // An external edit that lands in the same window must survive that echo.
        it.each([
            { description: 'drops the own echo once the save lands', events: [LATER], name: 'Saved here' },
            {
                description: 'keeps a newer external edit that the own echo arrived after',
                events: ['2026-01-01T00:02:00Z', LATER],
                name: 'Renamed by the agent',
            },
        ])('parks events that arrive during a save and $description', async ({ events, name }) => {
            await expectLogic(logic, () => {
                logic.actions.saveTemplate({ ...logic.values.template, name: 'Saved here' })
                events.forEach((updated_at) => resourceEditedLogic.actions.resourceEdited(edited({ updated_at })))
            })
                .toDispatchActions(['setDeferredExternalEdit', 'saveTemplateSuccess', 'replayDeferredExternalEdit'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: false, deferredExternalEdit: null })
            expect(logic.values.template.name).toBe(name)
        })

        // A failed reload leaves the stale copy on the form, so the conflict must stay visible with its retry.
        it('shows the banner when the reload of a clean form fails', async () => {
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [500, { detail: 'nope' }] },
            })

            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            })
                .toDispatchActions(['loadTemplateFailure'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: true, isSyncingExternalEdit: false })
            expect(logic.values.template.name).toBe('Existing')
        })

        it('reload from the banner replaces the unsaved edits with the server copy', async () => {
            logic.actions.setTemplateValue('name', 'My edit')
            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            }).toMatchValues({ externallyEdited: true })

            await expectLogic(logic, () => {
                logic.actions.syncExternalEdit()
            })
                .toDispatchActions(['loadTemplateSuccess'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                externallyEdited: false,
                isSyncingExternalEdit: false,
                templateChanged: false,
            })
            expect(logic.values.template.name).toBe('Renamed by the agent')
        })
    })

    describe('starting-point picker', () => {
        const AI_FIRST_FLAGS = [
            FEATURE_FLAGS.EMAIL_TEMPLATES_AI_FIRST_NEW,
            FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
        ]
        const NEW_PATH = '/workflows/library/templates/new'

        it.each([
            {
                description: 'opens for a brand-new template',
                props: { id: 'new' },
                expectedOpen: true,
            },
            {
                description: 'does not open when creating from a sent message',
                props: { id: 'new', messageId: 'message-id' },
                expectedOpen: false,
            },
            {
                description: 'does not open for an existing template',
                props: { id: 'existing-id' },
                expectedOpen: false,
            },
            // The AI composer is its own starting point, so the modal would cover it.
            {
                description: 'does not open while the AI composer is the page',
                props: { id: 'new' },
                flags: AI_FIRST_FLAGS,
                search: { mode: 'ai' },
                expectedOpen: false,
            },
            {
                description: 'opens for an AI URL when the variant is off',
                props: { id: 'new' },
                flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
                search: { mode: 'ai' },
                expectedOpen: true,
            },
        ])('$description', async ({ props, flags, search, expectedOpen }) => {
            if (flags) {
                featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
            }
            router.actions.push(NEW_PATH, search ?? {}, {})
            logic = messageTemplateLogic(props)
            logic.mount()

            await expectLogic(logic).toMatchValues({ templatePickerOpen: expectedOpen })
        })

        // The escape hatch only swaps a search param, so nothing remounts, and the picker has to follow the URL.
        it('opens when the URL switches to editor mode on the mounted page', async () => {
            featureFlagLogic.actions.setFeatureFlags(
                AI_FIRST_FLAGS,
                Object.fromEntries(AI_FIRST_FLAGS.map((flag) => [flag, true]))
            )
            router.actions.push(NEW_PATH, { mode: 'ai' }, {})
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toMatchValues({ templatePickerOpen: false })

            router.actions.push(NEW_PATH, { mode: 'editor' }, {})

            await expectLogic(logic).toMatchValues({ templatePickerOpen: true })
        })
    })

    const CODE_MANAGED = {
        id: 'existing-id',
        name: 'Welcome',
        description: 'Sent after signup',
        content: {
            templating: 'liquid',
            email: { subject: 'Welcome', html: '<p>Hi</p>', text: 'Hi', design: null, from: '', to: '' },
        },
        key: 'welcome',
        managed_by: 'code',
        source_repository: 'github.com/example/app',
        source_path: 'emails/welcome.html',
        source_ref: '3f2c1ab9d4e5f60718293a4b5c6d7e8f90a1b2c3',
        content_hash: 'v1:0000000000000000000000000000000000000000000000000000000000000000',
        change_prompt_starter: 'In `emails/welcome.html`, change ',
        change_prompt_context:
            'About this file:\n' +
            '- It is the PostHog email template with the key `welcome`.\n' +
            '- This file uses `{{ variables.first_name }}` and `{{ variables.confirm_url }}`.',
        change_prompt_variables: ['first_name', 'confirm_url'],
    }

    describe('code-managed source', () => {
        it.each([
            {
                description: 'a template made in PostHog has no source',
                served: { id: 'existing-id', name: 'Existing', managed_by: null },
                isCodeManaged: false,
                templateSource: null,
            },
            {
                description: 'a keyed template that PostHog still manages has no source',
                served: { ...CODE_MANAGED, managed_by: 'gui' },
                isCodeManaged: false,
                templateSource: null,
            },
            {
                description: 'a known host links the file, the repository and the shortened commit',
                served: CODE_MANAGED,
                isCodeManaged: true,
                templateSource: {
                    path: 'emails/welcome.html',
                    fileUrl:
                        'https://github.com/example/app/blob/3f2c1ab9d4e5f60718293a4b5c6d7e8f90a1b2c3/emails/welcome.html',
                    repository: 'github.com/example/app',
                    repositoryUrl: 'https://github.com/example/app',
                    ref: '3f2c1ab',
                    refUrl: 'https://github.com/example/app/commit/3f2c1ab9d4e5f60718293a4b5c6d7e8f90a1b2c3',
                },
            },
            {
                description: 'a branch links to the branch',
                served: { ...CODE_MANAGED, source_ref: 'main' },
                isCodeManaged: true,
                templateSource: expect.objectContaining({
                    ref: 'main',
                    refUrl: 'https://github.com/example/app/tree/main',
                }),
            },
            {
                description: 'an unknown host stays plain text',
                served: { ...CODE_MANAGED, source_repository: 'git.example.com/team/app' },
                isCodeManaged: true,
                templateSource: {
                    path: 'emails/welcome.html',
                    fileUrl: undefined,
                    repository: 'git.example.com/team/app',
                    repositoryUrl: undefined,
                    ref: '3f2c1ab',
                    refUrl: undefined,
                },
            },
            {
                description: 'an upload without a source shows none',
                served: { ...CODE_MANAGED, source_repository: null, source_path: null, source_ref: null },
                isCodeManaged: true,
                templateSource: null,
            },
        ])('$description', async ({ served, isCodeManaged, templateSource }) => {
            useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': served } })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadTemplateSuccess'])
                .toMatchValues({ isCodeManaged, templateSource })
        })
    })

    describe('code-managed template', () => {
        let patchBodies: Record<string, unknown>[]
        let createBodies: Record<string, unknown>[]
        let capture: jest.SpyInstance
        let writeText: jest.Mock

        beforeEach(async () => {
            jest.clearAllMocks()
            patchBodies = []
            createBodies = []
            capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            writeText = jest.fn().mockResolvedValue(undefined)
            Object.assign(navigator, { clipboard: { writeText } })
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': CODE_MANAGED },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': async ({
                        request,
                    }: {
                        request: Request
                    }) => {
                        patchBodies.push(await request.json())
                        return [200, { ...CODE_MANAGED, managed_by: 'gui' }]
                    },
                },
                post: {
                    '/api/environments/:team_id/messaging_templates/': async ({ request }: { request: Request }) => {
                        createBodies.push(await request.json())
                        return [201, { id: 'copy-id' }]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        })

        it('keeps its fields and never saves when they change', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTemplateValue('content.email.subject', 'Edited here')
                logic.actions.setTemplateValues({ name: 'Renamed here' })
                logic.actions.submitTemplate()
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ templateChanged: false })
            expect(logic.values.template.name).toBe('Welcome')
            expect(patchBodies).toEqual([])
        })

        it('duplicates as a copy without its key, ownership, source or hash', async () => {
            await expectLogic(logic, () => {
                logic.actions.duplicateTemplate()
            }).toFinishAllListeners()

            expect(createBodies).toEqual([
                { name: 'Welcome (copy)', description: 'Sent after signup', content: CODE_MANAGED.content },
            ])
            expect(capture).toHaveBeenCalledWith('message template duplicated', {
                template_id: 'existing-id',
                code_managed: true,
            })
        })

        it('becomes editable once released', async () => {
            await expectLogic(logic, () => {
                logic.actions.releaseTemplate()
            })
                .toDispatchActions(['releaseTemplateSuccess'])
                .toFinishAllListeners()

            expect(patchBodies).toEqual([{ managed_by: 'gui' }])
            logic.actions.setTemplateValue('name', 'Edited here')
            await expectLogic(logic).toMatchValues({ isCodeManaged: false, templateChanged: true })

            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            })
                .toDispatchActions(['saveTemplateSuccess'])
                .toFinishAllListeners()
            expect(patchBodies[1]).toMatchObject({ name: 'Edited here' })
            const serverOwnedFieldsSent = [
                'key',
                'managed_by',
                'source_repository',
                'source_path',
                'source_ref',
            ].filter((field) => field in patchBodies[1])
            expect(serverOwnedFieldsSent).toEqual([])
            expect(capture).toHaveBeenCalledWith('message template released from code', {
                template_id: 'existing-id',
            })
        })

        it.each([
            { description: 'the starter as served', sentence: 'In `emails/welcome.html`, change ' },
            { description: 'the starter without its trailing space', sentence: 'In `emails/welcome.html`, change' },
            { description: 'a blank sentence', sentence: '  \n' },
        ])('waits for a described change before it copies, given $description', async ({ sentence }) => {
            logic.actions.setChangeSentence(sentence)

            await expectLogic(logic).toMatchValues({
                copyAgentPromptDisabledReason: 'Describe the change first',
            })
        })

        it('starts from the server starter and keeps the sentence while the popover closes and reopens', async () => {
            await expectLogic(logic).toMatchValues({ changeSentence: 'In `emails/welcome.html`, change ' })

            logic.actions.setAgentPromptOpen(true)
            logic.actions.setChangeSentence('In `emails/welcome.html`, change the button to green.')
            logic.actions.setAgentPromptOpen(false)
            logic.actions.setAgentPromptOpen(true)

            await expectLogic(logic).toMatchValues({
                changeSentence: 'In `emails/welcome.html`, change the button to green.',
                copyAgentPromptDisabledReason: undefined,
            })
            expect(capture).toHaveBeenCalledWith('message template agent prompt opened', {
                template_id: 'existing-id',
                has_path: true,
                has_repository: true,
            })
        })

        it.each([
            {
                description: 'keeps the sentence when a reload serves the same starter',
                reloaded: CODE_MANAGED,
                changeSentence: 'In `emails/welcome.html`, change the button to green.',
            },
            {
                description: 'drops the sentence when a reload points the template at another file',
                reloaded: {
                    ...CODE_MANAGED,
                    source_path: 'emails/hello.html',
                    change_prompt_starter: 'In `emails/hello.html`, change ',
                },
                changeSentence: 'In `emails/hello.html`, change ',
            },
        ])('$description', async ({ reloaded, changeSentence }) => {
            logic.actions.setChangeSentence('In `emails/welcome.html`, change the button to green.')

            await expectLogic(logic, () => {
                logic.actions.loadTemplateSuccess(reloaded as any)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ changeSentence })
        })

        it('copies the sentence and the server context verbatim, and sends nothing', async () => {
            logic.actions.setAgentPromptOpen(true)
            logic.actions.setChangeSentence('In `emails/welcome.html`, change the button to green.')

            await expectLogic(logic, () => {
                logic.actions.copyAgentPrompt()
            }).toFinishAllListeners()

            expect(writeText).toHaveBeenCalledWith(
                'In `emails/welcome.html`, change the button to green.\n' +
                    '\n' +
                    'About this file:\n' +
                    '- It is the PostHog email template with the key `welcome`.\n' +
                    '- This file uses `{{ variables.first_name }}` and `{{ variables.confirm_url }}`.'
            )
            expect(patchBodies).toEqual([])
            expect(createBodies).toEqual([])
            await expectLogic(logic).toMatchValues({ agentPromptOpen: false })
            expect(mockToast.success).toHaveBeenCalledWith(
                'Prompt copied. Paste it into your coding agent. PostHog keeps sending the current version until your app sends or uploads the changed file.'
            )
            expect(capture).toHaveBeenCalledWith('message template agent prompt copied', {
                template_id: 'existing-id',
                has_path: true,
                has_repository: true,
                variable_count: 2,
            })
        })

        it.each([
            {
                description: 'with a plain-text part',
                text: 'Hi',
                droppedTextPart: true,
                toast: "Copied. Save it as the template's file. PostHog keeps sending the current version until your app sends or uploads the file. This file has no plain-text part. The next upload from this file removes the plain-text version.",
            },
            {
                description: 'without a plain-text part',
                text: ' ',
                droppedTextPart: false,
                toast: "Copied. Save it as the template's file. PostHog keeps sending the current version until your app sends or uploads the file.",
            },
        ])(
            'copies the published template as its HTML file $description, and sends nothing',
            async ({ text, toast, droppedTextPart }) => {
                logic.unmount()
                useMocks({
                    get: {
                        '/api/environments/:team_id/messaging_templates/:id/': {
                            ...CODE_MANAGED,
                            content: { ...CODE_MANAGED.content, email: { ...CODE_MANAGED.content.email, text } },
                        },
                    },
                })
                logic = messageTemplateLogic({ id: 'existing-id' })
                logic.mount()
                await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])

                await expectLogic(logic, () => {
                    logic.actions.copyHtmlFile()
                }).toFinishAllListeners()

                expect(writeText).toHaveBeenCalledWith('<head><title>Welcome</title></head><p>Hi</p>')
                expect(patchBodies).toEqual([])
                expect(createBodies).toEqual([])
                expect(mockToast.success).toHaveBeenCalledWith(toast)
                expect(capture).toHaveBeenCalledWith('message template html file copied', {
                    template_id: 'existing-id',
                    dropped_text_part: droppedTextPart,
                })
            }
        )
    })

    describe('claimed back by an upload while editing', () => {
        let serverTemplate: Record<string, unknown>
        let reloadStatus: number
        let createBodies: Record<string, unknown>[]

        const refuseSave = async (): Promise<void> => {
            serverTemplate = CODE_MANAGED
            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            })
                .toDispatchActions([
                    'saveTemplateFailure',
                    reloadStatus === 200 ? 'loadTemplateSuccess' : 'loadTemplateFailure',
                ])
                .toFinishAllListeners()
        }

        beforeEach(async () => {
            serverTemplate = { ...CODE_MANAGED, managed_by: 'gui' }
            reloadStatus = 200
            createBodies = []
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [reloadStatus, serverTemplate],
                },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [
                        403,
                        { type: 'invalid_request', code: 'immutable', detail: 'This template is managed by code.' },
                    ],
                },
                post: {
                    '/api/environments/:team_id/messaging_templates/': async ({ request }: { request: Request }) => {
                        createBodies.push(await request.json())
                        return [201, { id: 'copy-id' }]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])

            logic.actions.setTemplateValue('name', 'Welcome, edited here')
            logic.actions.setTemplateValue('content.email.subject', 'Edited subject')
        })

        it.each([
            { reload: 'succeeds', status: 200 },
            { reload: 'fails', status: 500 },
        ])('turns read-only and offers to duplicate the unsaved edits when the reload $reload', async ({ status }) => {
            reloadStatus = status
            await refuseSave()

            await expectLogic(logic).toMatchValues({
                isCodeManaged: true,
                templateChanged: false,
                refusedEdits: expect.objectContaining({ name: 'Welcome, edited here' }),
            })
            expect(logic.values.template.name).toBe('Welcome')
        })

        it('duplicates the unsaved edits without its key, ownership, source or hash', async () => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            await refuseSave()

            await expectLogic(logic, () => {
                logic.actions.duplicateWithMyChanges()
            }).toFinishAllListeners()

            expect(createBodies).toEqual([
                {
                    name: 'Welcome, edited here (copy)',
                    description: 'Sent after signup',
                    content: {
                        ...CODE_MANAGED.content,
                        email: { ...CODE_MANAGED.content.email, subject: 'Edited subject' },
                    },
                },
            ])
            await expectLogic(logic).toMatchValues({ refusedEdits: null })
            expect(capture).toHaveBeenCalledWith('message template duplicated', {
                template_id: 'existing-id',
                code_managed: true,
            })
        })
    })

    describe('run with PostHog Code', () => {
        const DESCRIBED = 'In `emails/welcome.html`, change the button to green. '
        let changeRequests: Record<string, unknown>[]
        let capture: jest.SpyInstance
        let served: {
            template: Record<string, unknown>
            integrations: Record<string, unknown>[]
            access: readonly [number, Record<string, unknown>]
        }

        beforeEach(() => {
            jest.clearAllMocks()
            changeRequests = []
            capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            served = {
                template: CODE_MANAGED,
                integrations: [{ id: 7, kind: 'github', display_name: 'example' }],
                access: [200, { allowed: true, reason: null }],
            }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [200, served.template],
                    '/api/projects/:team_id/desktop/access/': () => served.access,
                    '/api/projects/:team_id/integrations/': () => [200, { results: served.integrations }],
                },
                post: {
                    '/api/projects/:team_id/messaging_templates/:id/request_change/': async ({
                        request,
                    }: {
                        request: Request
                    }) => {
                        changeRequests.push(await request.json())
                        return [
                            201,
                            {
                                task_id: 'task-id',
                                task_url: 'http://localhost:8010/project/997/tasks/task-id',
                                repository: 'example/app',
                            },
                        ]
                    },
                },
            })
        })

        async function mountServing(overrides: Partial<typeof served> = {}): Promise<void> {
            served = { ...served, ...Object.fromEntries(Object.entries(overrides).filter(([, value]) => value)) }
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess']).toFinishAllListeners()
        }

        it('sends the sentence exactly as typed', async () => {
            await mountServing()
            logic.actions.setChangeSentence(DESCRIBED)

            await expectLogic(logic, () => {
                logic.actions.runWithPostHogCode()
            }).toFinishAllListeners()

            expect(changeRequests).toEqual([{ instruction: DESCRIBED }])
            expect(capture).toHaveBeenCalledWith('message template change run requested', {
                template_id: 'existing-id',
            })
        })

        it('starts one task when the button is clicked twice', async () => {
            await mountServing()
            logic.actions.setChangeSentence(DESCRIBED)

            await expectLogic(logic, () => {
                logic.actions.runWithPostHogCode()
                logic.actions.runWithPostHogCode()
            }).toFinishAllListeners()

            expect(changeRequests).toHaveLength(1)
        })

        it('links the task and clears the sentence once PostHog Code starts', async () => {
            await mountServing()
            logic.actions.setAgentPromptOpen(true)
            logic.actions.setChangeSentence(DESCRIBED)

            await expectLogic(logic, () => {
                logic.actions.runWithPostHogCode()
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                changeRun: expect.objectContaining({ task_id: 'task-id' }),
                changeSentence: 'In `emails/welcome.html`, change ',
                agentPromptOpen: false,
            })
            expect(mockToast.success).toHaveBeenCalledWith(
                "PostHog Code is working on it. It opens a pull request when it's done.",
                expect.objectContaining({ button: expect.objectContaining({ label: 'Open task' }) })
            )
        })

        it.each([
            {
                description: 'the server explains the refusal',
                response: [
                    400,
                    {
                        type: 'validation_error',
                        code: 'github_repository_not_connected',
                        detail: "This project's GitHub connection can't reach `example/app`.",
                        attr: null,
                        fix: 'Add the repository to the GitHub integration, then try again.',
                    },
                ],
                error: {
                    detail: "This project's GitHub connection can't reach `example/app`.",
                    fix: 'Add the repository to the GitHub integration, then try again.',
                },
                code: 'github_repository_not_connected',
            },
            {
                description: 'the server gives no reason',
                response: [500, {}],
                error: { detail: "PostHog Code couldn't start.", fix: 'Try again in a few minutes.' },
                code: null,
            },
        ])('keeps the sentence when $description', async ({ response, error, code }) => {
            await mountServing()
            useMocks({ post: { '/api/projects/:team_id/messaging_templates/:id/request_change/': () => response } })
            logic.actions.setAgentPromptOpen(true)
            logic.actions.setChangeSentence(DESCRIBED)

            await expectLogic(logic, () => {
                logic.actions.runWithPostHogCode()
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                changeRunError: error,
                changeSentence: DESCRIBED,
                agentPromptOpen: true,
                copyAgentPromptDisabledReason: undefined,
                runWithPostHogCodeDisabledReason: undefined,
            })
            expect(capture).toHaveBeenCalledWith('message template change run failed', {
                template_id: 'existing-id',
                code,
            })
        })

        it.each([
            { description: 'the organization can use PostHog Code', access: [200, { allowed: true }], available: true },
            {
                description: 'the organization cannot use PostHog Code',
                access: [200, { allowed: false, reason: null }],
                available: false,
            },
            { description: 'PostHog cannot check access', access: [503, { code: 'unavailable' }], available: false },
        ] as const)('offers the button only when $description', async ({ access, available }) => {
            await mountServing({ access })

            await expectLogic(logic).toMatchValues({ postHogCodeAvailable: available })
        })

        it.each([
            {
                description: 'the change is not described',
                sentence: 'In `emails/welcome.html`, change ',
                reason: 'Describe the change first',
            },
            {
                description: 'the template has no repository',
                template: { ...CODE_MANAGED, source_repository: null },
                reason: "PostHog doesn't know this template's GitHub repository",
            },
            {
                description: 'the repository is not on GitHub',
                template: { ...CODE_MANAGED, source_repository: 'gitlab.com/example/app' },
                reason: "PostHog doesn't know this template's GitHub repository",
            },
            {
                description: 'the project has no GitHub integration',
                integrations: [{ id: 8, kind: 'slack', display_name: 'Slack' }],
                reason: 'Connect GitHub to run PostHog Code',
            },
        ])('sends nothing when $description', async ({ sentence, template, integrations, reason }) => {
            await mountServing({ template, integrations })
            logic.actions.setChangeSentence(sentence ?? DESCRIBED)

            await expectLogic(logic, () => {
                logic.actions.runWithPostHogCode()
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ runWithPostHogCodeDisabledReason: reason })
            expect(changeRequests).toEqual([])
        })
    })

    describe('make transactional', () => {
        it('keeps edits made while the conversion runs', async () => {
            useMocks({
                post: {
                    '/api/projects/:team_id/messaging_templates/:id/make_transactional/': {
                        id: 'existing-id',
                        name: 'Existing',
                        transactional_hog_flow_id: 'flow-id',
                        updated_at: '2026-01-02T00:00:00Z',
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.makeTransactional()
                logic.actions.setTemplateValue('name', 'Renamed while converting')
            })
                .toDispatchActions(['makeTransactionalDone'])
                .toMatchValues({ transactionalHogFlowId: 'flow-id', templateChanged: true })

            expect(logic.values.template.name).toEqual('Renamed while converting')
        })
    })
})
