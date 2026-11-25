import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { delay } from 'lib/utils/async'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

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
                logic.actions.saveTemplate({ ...logic.values.template, id: 'existing-id', name: 'Existing' })
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

        it.each([
            {
                read: 'lands',
                exportEdit: (callback: (data: any) => void) => callback({ html: '<p>Mine</p>', design: { mine: 1 } }),
            },
            {
                read: 'fails',
                exportEdit: () => {
                    throw new Error('unreadable')
                },
            },
        ])(
            'shows the banner instead of reloading over an edit still in the canvas when its read $read',
            async ({ exportEdit }) => {
                const email = { subject: 'Hi', html: '<p>Old</p>', text: 'Old', design: null, from: '', to: '' }
                const templater = emailTemplaterLogic({
                    value: email,
                    onChange: (value) => logic.actions.setTemplateValue('content.email', value),
                    type: 'native_email_template',
                    layout: 'inline',
                })
                const unmountTemplater = templater.mount()
                templater.actions.setEmailEditorRef({
                    editor: {
                        loadDesign: jest.fn(),
                        addEventListener: jest.fn(),
                        exportHtml: exportEdit,
                        exportPlainText: (callback: (data: any) => void) => callback({ text: 'Mine' }),
                    },
                } as any)
                templater.actions.onEmailEditorReady()
                templater.actions.designUpdated()

                resourceEditedLogic.actions.resourceEdited(edited())

                await waitFor(() => expect(logic.values.externallyEdited).toBe(true))
                expect(logic.values.isSyncingExternalEdit).toBe(false)
                expect(logic.values.template.name).toBe('Existing')
                unmountTemplater()
            }
        )

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

    describe('transactional drafts', () => {
        const live = { templating: 'liquid', email: { subject: 'Live subject', html: '<p>Live</p>' } }
        const draft = { templating: 'liquid', email: { subject: 'Draft subject', html: '<p>Draft</p>' } }
        const serverTemplate = {
            id: 'existing-id',
            name: 'Existing',
            content: live,
            draft_content: draft,
            transactional_hog_flow_id: 'flow-id',
            sensitive: false,
            updated_at: '2026-01-01T00:00:00Z',
        }
        let bodies: Record<string, unknown>[]

        beforeEach(async () => {
            bodies = []
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                bodies.push(body)
                // Saving the content publishes it and the server clears the draft.
                return [
                    200,
                    'content' in body
                        ? { ...serverTemplate, ...body, draft_content: null }
                        : { ...serverTemplate, ...body, updated_at: '2026-01-01T00:01:00Z' },
                ]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': serverTemplate },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('edits the draft and saves edits to it without touching the live content', async () => {
            expect(logic.values.template.content).toEqual(draft)
            jest.useFakeTimers()
            const edited = { ...draft, email: { ...draft.email, subject: 'Edited subject' } }

            logic.actions.setTemplateValue('content', edited)
            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveDraftDone']).toMatchValues({
                hasDraft: true,
                hasUnsavedChanges: false,
            })

            expect(bodies).toEqual([{ draft_content: edited }])
        })

        it('saves an emptied email to the draft without the null design the server refuses', async () => {
            jest.useFakeTimers()
            const emptied = { ...draft, email: { ...draft.email, html: '', design: null } } as any

            logic.actions.setTemplateValue('content', emptied)
            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveDraftDone'])

            expect(bodies).toEqual([{ draft_content: { ...draft, email: { subject: 'Draft subject', html: '' } } }])
        })

        it('holds autosave while an edit from elsewhere is unresolved, then saves once the person keeps theirs', async () => {
            jest.useFakeTimers()
            const edited = { ...draft, email: { ...draft.email, subject: 'Edited subject' } }

            logic.actions.setExternallyEdited(true)
            logic.actions.setTemplateValue('content', edited)
            await jest.advanceTimersByTimeAsync(3000)
            expect(bodies).toEqual([])

            logic.actions.keepMyTemplateVersion()
            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveDraftDone'])
            expect(bodies).toEqual([{ draft_content: edited }])
        })

        it('protecting sensitive data saves only the flag, so the draft stays unpublished', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSensitive(true)
            }).toDispatchActions(['setSensitiveDone'])

            expect(bodies).toEqual([{ sensitive: true }])
            expect(logic.values.originalTemplate.sensitive).toBe(true)
            expect(logic.values.templateChanged).toBe(false)
            expect(logic.values.hasDraft).toBe(true)
        })

        it('publishing sends the content and leaves no draft behind', async () => {
            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            })
                .toDispatchActions(['saveTemplateSuccess'])
                .toMatchValues({ hasDraft: false, hasUnsavedChanges: false })

            expect(bodies).toHaveLength(1)
            expect(bodies[0].content).toEqual(draft)
            expect(bodies[0]).not.toHaveProperty('draft_content')
            expect(bodies[0]).not.toHaveProperty('sensitive')
        })
    })

    describe('typing while a save runs', () => {
        const email = { subject: 'Hi', html: '<p>Sent</p>', text: 'Sent', design: { body: { id: 'sent' } } }
        const typedEmail = { ...email, html: '<p>Typed</p>', text: 'Typed', design: { body: { id: 'typed' } } }
        let bodies: Record<string, any>[]
        let releaseSave: () => void
        let stored: Record<string, any>
        let confirmLeave: jest.SpyInstance

        afterEach(() => {
            confirmLeave.mockRestore()
            jest.useRealTimers()
        })

        beforeEach(() => {
            confirmLeave = jest.spyOn(window, 'confirm').mockReturnValue(true)
            bodies = []
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, any>
                bodies.push(body)
                if (bodies.length === 1) {
                    await new Promise<void>((resolve) => (releaseSave = resolve))
                }
                stored = { ...stored, ...body, ...('content' in body ? { draft_content: null } : {}) }
                return [200, stored]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, stored] },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                },
            })
        })

        const start = async (extra: Record<string, unknown> = {}): Promise<void> => {
            stored = {
                id: 'existing-id',
                name: 'Existing',
                description: '',
                content: { templating: 'liquid', email },
                ...extra,
            }
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
            logic.actions.setTemplateValue('name', 'Sent name')
            logic.actions.submitTemplate()
            await waitFor(() => expect(bodies).toHaveLength(1))
        }
        const land = async (): Promise<void> => {
            releaseSave()
            await expectLogic(logic).toDispatchActions(['saveTemplateSuccess'])
        }

        it.each([
            { field: 'the email', path: 'content.email', value: typedEmail, read: (body: any) => body.content.email },
            { field: 'the name', path: 'name', value: 'Typed name', read: (body: any) => body.name },
            { field: 'the description', path: 'description', value: 'Typed', read: (body: any) => body.description },
        ])('keeps $field, leaves it unsaved, and the next save stores it', async ({ path, value, read }) => {
            await start()

            logic.actions.setTemplateValue(path, value)
            await land()

            expect(read(bodies[0])).not.toEqual(value)
            expect(read(logic.values.template)).toEqual(value)
            expect(logic.values.templateChanged).toBe(true)
            expect(confirmLeave).not.toHaveBeenCalled()

            logic.actions.submitTemplate()
            await waitFor(() => expect(bodies).toHaveLength(2))
            expect(read(bodies[1])).toEqual(value)
        })

        it('has nothing unsaved when nothing was typed', async () => {
            await start()
            await land()

            expect(logic.values.templateChanged).toBe(false)
            expect(logic.values.template).toMatchObject({ name: 'Sent name', content: { email } })
        })

        it('saves an edit typed during a publish as the next draft', async () => {
            await start({ transactional_hog_flow_id: 'flow-id' })

            logic.actions.setTemplateValue('content.email', typedEmail)
            jest.useFakeTimers()
            releaseSave()
            await jest.advanceTimersByTimeAsync(2000)

            expect(bodies[0].content.email).toEqual(email)
            expect(bodies[1]).toEqual({ draft_content: { templating: 'liquid', email: typedEmail } })
        })

        it('discards the draft only after a publish lands, and keeps the published email', async () => {
            await start({
                transactional_hog_flow_id: 'flow-id',
                draft_content: { templating: 'liquid', email: typedEmail },
            })

            logic.actions.confirmDiscardDraft()
            await new Promise(process.nextTick)
            expect(bodies).toHaveLength(1)
            releaseSave()
            await expectLogic(logic)
                .toDispatchActions(['saveTemplateSuccess', 'discardDraftDone'])
                .toFinishAllListeners()

            expect(logic.values.template.content.email).toEqual(typedEmail)
            expect(logic.values.draftOutOfDate).toBe(false)
            expect(logic.values.hasDraft).toBe(false)
        })
    })

    describe('make transactional', () => {
        test.each([
            ['an edit made while it runs', true],
            ['no edits', false],
        ])('shows the stored sender and keeps the form, with %s', async (_name, editWhileConverting) => {
            useMocks({
                post: {
                    '/api/projects/:team_id/messaging_templates/:id/make_transactional/': {
                        id: 'existing-id',
                        name: 'Existing',
                        content: { templating: 'liquid', email: { subject: 'Hi', from: { integrationId: 9 } } },
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
                if (editWhileConverting) {
                    logic.actions.setTemplateValue('name', 'Renamed while converting')
                }
            })
                .toDispatchActions(['makeTransactionalDone'])
                .toMatchValues({ transactionalHogFlowId: 'flow-id', templateChanged: editWhileConverting })

            expect(logic.values.template.content.email.from).toEqual({ integrationId: 9 })
            if (editWhileConverting) {
                expect(logic.values.template.name).toEqual('Renamed while converting')
            }
        })
    })

    describe('tags', () => {
        let patches: unknown[]

        const tagMocks = (status: number): Parameters<typeof useMocks>[0] => ({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': { id: 'existing-id', name: 'A', tags: ['old'] },
            },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    patches.push(body)
                    return [status, { id: 'existing-id', name: 'A', ...body }]
                },
            },
        })

        const mountLoaded = async (): Promise<void> => {
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        }

        beforeEach(() => {
            patches = []
        })

        it('keeps every tag added before the first save answers', async () => {
            useMocks(tagMocks(200))
            await mountLoaded()
            // The menu bar has no state of its own, so it adds to whatever tags the template shows.
            logic.actions.saveTags([...(logic.values.template.tags ?? []), 'a'])
            logic.actions.saveTags([...(logic.values.template.tags ?? []), 'b'])
            expect(logic.values.template.tags).toEqual(['old', 'a', 'b'])
            expect(logic.values.templateChanged).toBe(false)

            await expectLogic(logic).toFinishAllListeners()
            expect(patches).toEqual([{ tags: ['old', 'a', 'b'] }])
            expect(logic.values.template.tags).toEqual(['old', 'a', 'b'])
        })

        it('sends the next tags after the save before them answers, also when the person leaves', async () => {
            const mocks = tagMocks(200)
            const answers: (() => void)[] = []
            useMocks({
                ...mocks,
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        patches.push(body)
                        await new Promise<void>((resolve) => answers.push(resolve))
                        return [200, { id: 'existing-id', name: 'A', ...body }]
                    },
                },
            })
            await mountLoaded()
            logic.actions.saveTags(['old', 'a'])
            await waitFor(() => expect(answers).toHaveLength(1))
            logic.actions.saveTags(['old', 'a', 'b'])
            logic.unmount()
            await delay(100)
            expect(patches).toEqual([{ tags: ['old', 'a'] }])

            answers[0]()
            // Coming back waits for both, so the page never shows tags from before them.
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await waitFor(() => expect(patches).toEqual([{ tags: ['old', 'a'] }, { tags: ['old', 'a', 'b'] }]))
            expect(logic.values.originalTemplate.id).not.toBe('existing-id')
            answers[1]()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        })

        it('keeps a tag added while the template saves', async () => {
            const mocks = tagMocks(200)
            let answerSave: (() => void) | undefined
            useMocks({
                ...mocks,
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        patches.push(body)
                        if (body.tags) {
                            return [200, { id: 'existing-id', name: 'A', tags: body.tags }]
                        }
                        await new Promise<void>((resolve) => (answerSave = resolve))
                        return [200, { id: 'existing-id', name: 'A', tags: ['old'] }]
                    },
                },
            })
            await mountLoaded()
            logic.actions.saveTemplate(logic.values.template)
            await waitFor(() => expect(answerSave).toBeTruthy())
            logic.actions.saveTags(['old', 'a'])
            await waitFor(() => expect(patches).toContainEqual({ tags: ['old', 'a'] }))
            answerSave?.()
            await expectLogic(logic).toDispatchActions(['saveTemplateSuccess']).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old', 'a'])
            expect(logic.values.templateChanged).toBe(false)
        })

        it('goes back to the saved tags when the save fails', async () => {
            useMocks(tagMocks(500))
            await mountLoaded()
            logic.actions.saveTags(['old', 'a'])
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old'])
        })
    })
})
