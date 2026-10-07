import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { NEW_TEMPLATE } from './constants'
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
            {
                missing: 'name',
                prefill: { key: 'content.email.subject', value: 'Welcome' },
                toast: 'Name is required',
            },
            {
                missing: 'subject',
                prefill: { key: 'name', value: 'Welcome email' },
                toast: 'Subject is required',
            },
        ])('toasts when the $missing is missing', async ({ prefill, toast }) => {
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()

            logic.actions.setTemplateValue(prefill.key, prefill.value)
            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            }).toDispatchActions(['submitTemplateFailure'])

            expect(mockToast.error).toHaveBeenCalledWith(toast)
        })
    })

    it.each([
        { description: 'creating a template', id: 'new', method: 'post', status: 201, outcome: 'saveTemplateSuccess' },
        {
            description: 'saving an existing template',
            id: 'existing-id',
            method: 'patch',
            status: 200,
            outcome: 'saveTemplateSuccess',
        },
        { description: 'a failed save', id: 'new', method: 'post', status: 500, outcome: 'saveTemplateFailure' },
    ])('keeps the form submitting until $description finishes', async ({ id, method, status, outcome }) => {
        let finishSave!: () => void
        const saveHeld = new Promise<void>((resolve) => {
            finishSave = resolve
        })
        const save = jest.fn(async () => {
            await saveHeld
            return [status, { id: 'saved-id', name: 'Welcome email', content: { email: { subject: 'Hello' } } }]
        })
        useMocks({
            [method]: {
                '/api/environments/:team_id/messaging_templates/': save,
                '/api/environments/:team_id/messaging_templates/:id/': save,
            },
        })
        logic = messageTemplateLogic({ id })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setTemplateValues({ id, name: 'Welcome email', content: { email: { subject: 'Hello' } } })

        logic.actions.submitTemplate()
        await expectLogic(logic).toDispatchActions(['saveTemplate'])
        expect(logic.values.isTemplateSubmitting).toBe(true)

        finishSave()
        await expectLogic(logic).toDispatchActions([outcome])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isTemplateSubmitting).toBe(false)
        expect(save).toHaveBeenCalledTimes(1)
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
                logic.actions.saveTemplate({ ...NEW_TEMPLATE, id: 'existing-id', name: 'Existing' })
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

    describe('creating a template', () => {
        const content = { email: { subject: 'Hello' } }
        let finishCreate: () => void
        let loadedIds: string[]
        let confirmSpy: jest.SpyInstance
        let otherLogics: ReturnType<typeof messageTemplateLogic.build>[]

        const mountTemplateLogic = (id: string): ReturnType<typeof messageTemplateLogic.build> => {
            const templateLogic = messageTemplateLogic({ id })
            templateLogic.mount()
            otherLogics.push(templateLogic)
            return templateLogic
        }

        const finishTheCreate = async (): Promise<void> => {
            finishCreate()
            await expectLogic(logic).toDispatchActions(['saveTemplateSuccess']).toFinishAllListeners()
        }

        beforeEach(async () => {
            const createHeld = new Promise<void>((resolve) => {
                finishCreate = resolve
            })
            loadedIds = []
            otherLogics = []
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': (req) => {
                        loadedIds.push(String(req.params.id))
                        return [200, { id: req.params.id, name: 'Loaded', content }]
                    },
                },
                post: {
                    '/api/environments/:team_id/messaging_templates/': async () => {
                        await createHeld
                        return [
                            201,
                            { id: 'created-id', name: 'Welcome email', content, updated_at: '2026-01-01T00:00:00Z' },
                        ]
                    },
                },
            })
            confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()
            logic.actions.setTemplateValues({ name: 'Welcome email', content })
            logic.actions.submitTemplate()
            await expectLogic(logic).toDispatchActions(['saveTemplate'])
        })

        afterEach(() => {
            otherLogics.forEach((templateLogic) => templateLogic.unmount())
            confirmSpy.mockRestore()
        })

        it.each([
            { description: 'the saved copy', typed: null, name: 'Welcome email', subject: 'Hello', changed: false },
            {
                description: 'the edits typed during the create',
                typed: { name: 'Typed name', subject: 'Typed subject' },
                name: 'Typed name',
                subject: 'Typed subject',
                changed: true,
            },
        ])('opens it at its own URL with $description and no reload', async ({ typed, name, subject, changed }) => {
            if (typed) {
                logic.actions.setTemplateValue('name', typed.name)
                logic.actions.setTemplateValue('content.email.subject', typed.subject)
            }

            await finishTheCreate()
            const created = mountTemplateLogic('created-id')

            expect(router.values.location.pathname).toContain(urls.workflowsLibraryTemplate('created-id'))
            expect(confirmSpy).not.toHaveBeenCalled()
            await expectLogic(created).toMatchValues({ templateLoading: false, templateChanged: changed })
            expect(created.values.template).toMatchObject({ id: 'created-id', name, content: { email: { subject } } })
            expect(created.values.originalTemplate.name).toBe('Welcome email')
            await expectLogic(created).toFinishAllListeners()
            expect(loadedIds).toEqual([])

            created.unmount()
            otherLogics = otherLogics.filter((templateLogic) => templateLogic !== created)
            await expectLogic(mountTemplateLogic('created-id')).toDispatchActions(['loadTemplateSuccess'])
            expect(loadedIds).toEqual(['created-id'])
        })

        it('keeps the typed edits and their conflict reload here, and loads it later, when another unsaved form blocked the redirect', async () => {
            const otherForm = mountTemplateLogic('other-id')
            await expectLogic(otherForm).toDispatchActions(['loadTemplateSuccess'])
            otherForm.actions.setTemplateValue('name', 'Unsaved elsewhere')
            confirmSpy.mockReturnValue(false)
            logic.actions.setTemplateValue('name', 'Typed name')

            await finishTheCreate()

            expect(router.values.location.pathname).not.toContain(urls.workflowsLibraryTemplate('created-id'))
            await expectLogic(logic).toMatchValues({ templateChanged: true })
            expect(logic.values.template).toMatchObject({ id: 'created-id', name: 'Typed name' })
            resourceEditedLogic.actions.resourceEdited({
                notification_type: 'resource_edited',
                team_id: 1,
                resource_type: 'MessageTemplate',
                resource_id: 'created-id',
                updated_at: '2026-01-01T00:01:00Z',
                actor_user_id: null,
            })
            await expectLogic(logic).toMatchValues({ externallyEdited: true })

            await expectLogic(logic, () => logic.actions.syncExternalEdit()).toDispatchActions(['loadTemplateSuccess'])
            expect(loadedIds).toEqual(['other-id', 'created-id'])
            expect(logic.values.template).toMatchObject({ id: 'created-id', name: 'Loaded' })
            const created = mountTemplateLogic('created-id')
            await expectLogic(created).toDispatchActions(['loadTemplateSuccess'])
            expect(created.values.template.name).toBe('Loaded')
        })
    })

    describe('while a save is in flight', () => {
        let finishSave: () => void
        let confirmSpy: jest.SpyInstance

        beforeEach(async () => {
            const saveHeld = new Promise<void>((resolve) => {
                finishSave = resolve
            })
            const content = { email: { subject: 'Hello' } }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': {
                        id: 'existing-id',
                        name: 'Existing',
                        content,
                    },
                },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': async () => {
                        await saveHeld
                        return [200, { id: 'existing-id', name: 'Saved', content }]
                    },
                },
            })
            confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            router.actions.push(urls.workflowsLibraryTemplate('existing-id'))
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
            logic.actions.setTemplateValue('name', 'Saved')
            logic.actions.submitTemplate()
            await expectLogic(logic).toDispatchActions(['saveTemplate'])
        })

        afterEach(() => {
            confirmSpy.mockRestore()
        })

        it.each([
            {
                description: 'keeps edits typed during the save',
                duringSave: () => logic.actions.setTemplateValue('name', 'Typed while saving'),
                name: 'Typed while saving',
                changed: true,
            },
            {
                description: 'shows the saved copy after a discard during the save',
                duringSave: () => logic.actions.resetTemplate(logic.values.originalTemplate),
                name: 'Saved',
                changed: false,
            },
        ])('keeps the editor on screen and $description', async ({ duringSave, name, changed }) => {
            expect(logic.values.templateLoading).toBe(false)
            duringSave()

            finishSave()
            await expectLogic(logic).toDispatchActions(['saveTemplateSuccess']).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ templateChanged: changed })
            expect(logic.values.template.name).toBe(name)
            expect(logic.values.originalTemplate.name).toBe('Saved')
            expect(confirmSpy).not.toHaveBeenCalled()
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
                logic.actions.saveTemplate(logic.values.template)
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
})
