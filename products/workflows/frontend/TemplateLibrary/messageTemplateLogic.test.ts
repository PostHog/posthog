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
        info: jest.fn(),
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

        const changedElsewhere = { content: { ...live, email: { ...live.email, subject: 'Changed elsewhere' } } }
        const useServerCopy = (server: Record<string, unknown>): void => {
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': {
                        ...serverTemplate,
                        ...server,
                        updated_at: '2026-01-01T00:02:00Z',
                    },
                },
            })
        }
        const reloadAfterEditElsewhere = async (): Promise<void> => {
            await expectLogic(logic, () => logic.actions.syncExternalEdit()).toDispatchActions(['loadTemplateSuccess'])
        }

        it.each([
            { case: 'removed it', server: { ...changedElsewhere, draft_content: null }, banner: true },
            { case: 'published it', server: { content: draft, draft_content: null }, banner: false },
        ])(
            'a reload after an edit from elsewhere that $case keeps the typed draft: $banner',
            async ({ server, banner }) => {
                useServerCopy(server)
                await reloadAfterEditElsewhere()

                expect(logic.values.externallyEdited).toBe(banner)
                expect(logic.values.template.content).toEqual(draft)
            }
        )

        it('reloads to the other version on the first click when the banner asks about unsaved typing', async () => {
            const typed = { ...draft, email: { ...draft.email, subject: 'Typed, not saved yet' } }
            logic.actions.setExternallyEdited(true)
            logic.actions.setTemplateValue('content', typed)
            useServerCopy({ ...changedElsewhere, draft_content: null })

            await reloadAfterEditElsewhere()

            expect(logic.values.externallyEdited).toBe(false)
            expect(logic.values.template.content).toEqual(changedElsewhere.content)
        })

        it('asks nothing when the saved draft differs from the server copy only in what the server drops', async () => {
            logic.actions.saveDraftDone(
                { ...draft, email: { ...draft.email, design: null } } as any,
                '2026-01-01T00:01:00Z'
            )
            useServerCopy({ name: 'Renamed elsewhere' })

            await reloadAfterEditElsewhere()

            expect(logic.values.externallyEdited).toBe(false)
        })

        it('asks nothing when the server stored the draft trimmed and only metadata changed elsewhere', async () => {
            jest.useFakeTimers()
            const trimmed = { ...draft, email: { ...draft.email, subject: 'Typed subject' } }
            useMocks({
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': () => [
                        200,
                        { ...serverTemplate, draft_content: trimmed, updated_at: '2026-01-01T00:01:00Z' },
                    ],
                },
            })
            logic.actions.setTemplateValue('content', {
                ...draft,
                email: { ...draft.email, subject: 'Typed subject ' },
            })
            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveDraftDone'])
            useServerCopy({ name: 'Renamed elsewhere', draft_content: trimmed })

            await reloadAfterEditElsewhere()

            expect(logic.values.externallyEdited).toBe(false)
        })

        it('saves the typed draft again when the person keeps theirs after it was removed elsewhere', async () => {
            jest.useFakeTimers()
            useServerCopy({ ...changedElsewhere, draft_content: null })
            await reloadAfterEditElsewhere()

            logic.actions.keepMyTemplateVersion()
            await jest.advanceTimersByTimeAsync(1500)
            await expectLogic(logic).toDispatchActions(['saveDraftDone'])
            expect(bodies).toEqual([{ draft_content: draft }])
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

        it('publishing sends the content and leaves out settings and draft_content', async () => {
            logic.unmount()
            const sensitiveServerTemplate = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: true,
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': sensitiveServerTemplate },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        bodies.push(body)
                        return [200, { ...sensitiveServerTemplate, ...body, draft_content: null }]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.hasDraft).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            }).toFinishAllListeners()

            expect(bodies).toHaveLength(1)
            expect(bodies[0].content).toEqual(draft)
            expect(bodies[0]).not.toHaveProperty('draft_content')
            expect(bodies[0]).not.toHaveProperty('sensitive')
            expect(bodies[0]).not.toHaveProperty('click_tracking_enabled')
            expect(logic.values.hasDraft).toBe(false)
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it.each([
            { description: 'reloads newer published content on a clean form', dirty: false },
            { description: 'flags an external conflict, preserves local edits, and stops autosave', dirty: true },
        ])('reconciles a concurrent publish during a click tracking save: $description', async ({ dirty }) => {
            logic.unmount()
            const sensitiveServerTemplate = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null as boolean | null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const publishedElsewhere = {
                templating: 'liquid' as const,
                email: { subject: 'Published elsewhere', html: '<p>New live</p>' },
            }
            const unsavedEdit = {
                templating: 'liquid' as const,
                email: { subject: 'Unsaved local edit', html: '<p>Local</p>' },
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': sensitiveServerTemplate },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        bodies.push(body)
                        return [
                            200,
                            {
                                ...sensitiveServerTemplate,
                                ...body,
                                content: publishedElsewhere,
                                draft_content: null,
                                updated_at: '2026-01-01T00:02:00Z',
                            },
                        ]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            if (dirty) {
                logic.actions.setTemplateValue('content', unsavedEdit)
            }

            logic.actions.setClickTrackingEnabled(true)
            resourceEditedLogic.actions.resourceEdited({
                notification_type: 'resource_edited',
                team_id: 1,
                resource_type: 'MessageTemplate',
                resource_id: 'existing-id',
                updated_at: '2026-01-01T00:01:00Z',
                actor_user_id: null,
            })
            await jest.advanceTimersByTimeAsync(3000)
            await expectLogic(logic).toFinishAllListeners()

            expect(bodies).toEqual([{ click_tracking_enabled: true }])
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
            expect(logic.values.externallyEdited).toBe(dirty)
            expect(logic.values.hasDraft).toBe(dirty)
            expect(logic.values.template.content).toEqual(dirty ? unsavedEdit : publishedElsewhere)
        })

        it('waits for an in-flight draft save before toggling click tracking and does not raise a false conflict', async () => {
            logic.unmount()
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                draft_content: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const firstEdit = {
                templating: 'liquid' as const,
                email: { subject: 'Plain text edit ', html: '', design: null },
            } as any
            const secondEdit = {
                templating: 'liquid' as const,
                email: { subject: 'Follow-up edit', html: '', design: null },
            } as any
            let releaseDraftSave!: () => void
            const draftSaveGate = new Promise<void>((resolve) => {
                releaseDraftSave = resolve
            })
            let tick = 1
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, currentServer] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        bodies.push(body)
                        if ('draft_content' in body && tick === 1) {
                            await draftSaveGate
                        }
                        const normalizedBody =
                            'draft_content' in body && body.draft_content
                                ? {
                                      ...body,
                                      draft_content: {
                                          ...(body.draft_content as Record<string, any>),
                                          email: {
                                              ...(body.draft_content as Record<string, any>).email,
                                              subject: (body.draft_content as Record<string, any>).email.subject.trim(),
                                          },
                                      },
                                  }
                                : body
                        currentServer = {
                            ...currentServer,
                            ...normalizedBody,
                            updated_at: `2026-01-01T00:0${tick++}:00Z`,
                        }
                        return [200, currentServer]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            logic.actions.setTemplateValue('content', firstEdit)
            await jest.advanceTimersByTimeAsync(1500)
            expect(bodies).toEqual([
                { draft_content: { templating: 'liquid', email: { subject: 'Plain text edit ', html: '' } } },
            ])

            logic.actions.setClickTrackingEnabled(true)
            releaseDraftSave()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(bodies).toEqual([
                { draft_content: { templating: 'liquid', email: { subject: 'Plain text edit ', html: '' } } },
                { click_tracking_enabled: true },
            ])
            expect(logic.values.externallyEdited).toBe(false)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)

            logic.actions.setTemplateValue('content', secondEdit)
            logic.actions.setClickTrackingEnabled(false)
            await jest.advanceTimersByTimeAsync(200)
            expect(logic.values.externallyEdited).toBe(false)

            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toFinishAllListeners()
            expect(bodies.at(-1)).toEqual({
                draft_content: { templating: 'liquid', email: { subject: 'Follow-up edit', html: '' } },
            })
        })

        it('keeps a discarded draft cleared when discard overlaps a click tracking save', async () => {
            logic.unmount()
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            let releaseSettingSave!: () => void
            const settingSaveGate = new Promise<void>((resolve) => {
                releaseSettingSave = resolve
            })
            let tick = 1
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, currentServer] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        bodies.push(body)
                        if ('click_tracking_enabled' in body) {
                            await settingSaveGate
                        }
                        currentServer = {
                            ...currentServer,
                            ...body,
                            updated_at: `2026-01-01T00:0${tick++}:00Z`,
                        }
                        return [200, currentServer]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            logic.actions.setClickTrackingEnabled(true)
            logic.actions.confirmDiscardDraft()
            releaseSettingSave()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(bodies).toEqual([{ click_tracking_enabled: true }, { draft_content: null }])
            expect(logic.values.hasDraft).toBe(false)
            expect(logic.values.template.content).toEqual(live)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
        })

        it('ignores a stale out-of-order setting response after a newer publish and subsequent edit', async () => {
            logic.unmount()
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const postPublishEdit = {
                templating: 'liquid' as const,
                email: { subject: 'Post-publish edit', html: '<p>Next draft</p>' },
            }
            let releaseStaleSetting!: () => void
            const staleSettingGate = new Promise<void>((resolve) => {
                releaseStaleSetting = resolve
            })
            let settingRequestSent!: () => void
            const settingRequestArrived = new Promise<void>((resolve) => {
                settingRequestSent = resolve
            })
            let publishDone!: () => void
            const publishFinished = new Promise<void>((resolve) => {
                publishDone = resolve
            })
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                bodies.push(body)
                if ('click_tracking_enabled' in body) {
                    const earlierSnapshot = {
                        ...currentServer,
                        ...body,
                        draft_content: draft,
                        updated_at: '2026-01-01T00:01:00Z',
                    }
                    settingRequestSent()
                    await staleSettingGate
                    return [200, earlierSnapshot]
                }
                if ('draft_content' in body) {
                    currentServer = {
                        ...currentServer,
                        ...body,
                        updated_at: '2026-01-01T00:03:00Z',
                    }
                    return [200, currentServer]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    click_tracking_enabled: true,
                    draft_content: null,
                    updated_at: '2026-01-01T00:02:00Z',
                }
                publishDone()
                return [200, currentServer]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, currentServer] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.hasDraft).toBe(true)
            jest.useFakeTimers()

            logic.actions.setClickTrackingEnabled(true)
            await settingRequestArrived
            logic.actions.submitTemplate()
            await publishFinished
            await jest.advanceTimersByTimeAsync(10)

            logic.actions.setTemplateValue('content', postPublishEdit)
            releaseStaleSetting()
            await jest.advanceTimersByTimeAsync(10)

            expect(logic.values.hasDraft).toBe(false)
            expect(logic.values.externallyEdited).toBe(false)
            expect(logic.values.template.content).toEqual(postPublishEdit)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)

            resourceEditedLogic.actions.resourceEdited({
                notification_type: 'resource_edited',
                team_id: 1,
                resource_type: 'MessageTemplate',
                resource_id: 'existing-id',
                updated_at: '2026-01-01T00:01:30Z',
                actor_user_id: null,
            })
            await jest.advanceTimersByTimeAsync(10)
            expect(logic.values.externallyEdited).toBe(false)

            await jest.advanceTimersByTimeAsync(3500)
            await expectLogic(logic).toFinishAllListeners()
            expect(bodies.at(-1)).toEqual({ draft_content: postPublishEdit })
        })

        it('keeps a newer click tracking setting and reloads newer server content when an older publish response arrives after it', async () => {
            logic.unmount()
            const publishedByOtherTab = {
                templating: 'liquid' as const,
                email: { subject: 'Published by other tab', html: '<p>Newer publish</p>' },
            }
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null as boolean | null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            let releasePublish!: () => void
            const publishGate = new Promise<void>((resolve) => {
                releasePublish = resolve
            })
            let publishStarted!: () => void
            const publishArrived = new Promise<void>((resolve) => {
                publishStarted = resolve
            })
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                bodies.push(body)
                if ('click_tracking_enabled' in body) {
                    currentServer = {
                        ...currentServer,
                        content: publishedByOtherTab,
                        draft_content: null,
                        click_tracking_enabled: true,
                        updated_at: '2026-01-01T00:02:00Z',
                    }
                    return [200, currentServer]
                }
                publishStarted()
                await publishGate
                return [
                    200,
                    {
                        ...serverTemplate,
                        ...body,
                        sensitive: true,
                        draft_content: null,
                        click_tracking_enabled: null,
                        updated_at: '2026-01-01T00:01:00Z',
                    },
                ]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, currentServer] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            logic.actions.setClickTrackingEnabled(true)
            logic.actions.submitTemplate()
            await publishArrived
            await jest.advanceTimersByTimeAsync(10)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)

            releasePublish()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.hasDraft).toBe(false)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
            expect(logic.values.template.content).toEqual(publishedByOtherTab)
        })

        it('reconciles concurrent remote tags and preserves pending or newly completed local tag writes', async () => {
            logic.unmount()
            let releaseLocalTag!: () => void
            const localTagGate = new Promise<void>((resolve) => {
                releaseLocalTag = resolve
            })
            let releaseDelayedSetting!: () => void
            const delayedSettingGate = new Promise<void>((resolve) => {
                releaseDelayedSetting = resolve
            })
            let delayedSettingStarted!: () => void
            const delayedSettingArrived = new Promise<void>((resolve) => {
                delayedSettingStarted = resolve
            })
            let holdNextSetting = false
            let holdNextTag = false
            let tick = 1
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                tags: ['old'],
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                if ('tags' in body) {
                    if (holdNextTag) {
                        holdNextTag = false
                        await localTagGate
                    }
                    // Tag-only PATCH updates tags without changing updated_at or click_tracking_enabled.
                    currentServer = { ...currentServer, tags: body.tags as string[] }
                    return [200, { ...currentServer }]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    updated_at: `2026-01-01T00:0${tick++}:00Z`,
                }
                const snapshot = { ...currentServer }
                if (holdNextSetting) {
                    holdNextSetting = false
                    delayedSettingStarted()
                    await delayedSettingGate
                }
                return [200, snapshot]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // Another tab adds 'remote' before our setting PATCH runs: reconcile it cleanly.
            currentServer = { ...currentServer, tags: ['old', 'remote'] }
            logic.actions.setClickTrackingEnabled(true)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old', 'remote'])
            expect(logic.values.originalTemplate.tags).toEqual(['old', 'remote'])

            // Local tag write still in flight when a setting PATCH completes: keep local tags.
            holdNextTag = true
            logic.actions.saveTags(['old', 'remote', 'local'])
            logic.actions.setClickTrackingEnabled(false)
            await waitFor(() => expect(logic.values.isSavingClickTracking).toBe(false))
            expect(logic.values.template.tags).toEqual(['old', 'remote', 'local'])

            releaseLocalTag()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old', 'remote', 'local'])
            expect(currentServer.click_tracking_enabled).toBe(null)

            // Delayed setting response captured before a local tag write finishes: do not revert tags.
            holdNextSetting = true
            logic.actions.setClickTrackingEnabled(true)
            await delayedSettingArrived
            logic.actions.saveTags(['old', 'remote', 'local', 'after-setting'])
            await waitFor(() => expect(currentServer.tags).toEqual(['old', 'remote', 'local', 'after-setting']))

            releaseDelayedSetting()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old', 'remote', 'local', 'after-setting'])
            expect(logic.values.originalTemplate.tags).toEqual(['old', 'remote', 'local', 'after-setting'])
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
        })

        it('reconciles remote tags from a delayed setting response when a concurrent local tag write fails', async () => {
            logic.unmount()
            let releaseDelayedSetting!: () => void
            const delayedSettingGate = new Promise<void>((resolve) => {
                releaseDelayedSetting = resolve
            })
            let delayedSettingStarted!: () => void
            const delayedSettingArrived = new Promise<void>((resolve) => {
                delayedSettingStarted = resolve
            })
            const tagsAfterRemoteEdit = ['old', 'remote']
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                tags: ['old'],
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                if ('tags' in body) {
                    return [500, { detail: 'Tag save failed' }]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    tags: tagsAfterRemoteEdit,
                    updated_at: '2026-01-01T00:01:00Z',
                }
                const snapshot = { ...currentServer }
                delayedSettingStarted()
                await delayedSettingGate
                return [200, snapshot]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setClickTrackingEnabled(true)
            await delayedSettingArrived
            logic.actions.saveTags(['old', 'failed-local'])
            await waitFor(() => expect(logic.values.failedTagSaves).toBe(1))
            expect(logic.values.template.tags).toEqual(['old'])

            releaseDelayedSetting()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.template.tags).toEqual(['old', 'remote'])
            expect(logic.values.originalTemplate.tags).toEqual(['old', 'remote'])
        })

        const mountMockEmailTemplater = (
            targetLogic: ReturnType<typeof messageTemplateLogic.build>,
            exportGate?: Promise<void>
        ): {
            emitDesignUpdated: () => void
            unmount: () => void
        } => {
            const editorListeners: Record<string, () => void> = {}
            const templater = emailTemplaterLogic({
                value: targetLogic.values.template.content.email,
                onChange: (value) => targetLogic.actions.setTemplateValue('content.email', value),
                type: 'native_email_transactional_template',
                layout: 'inline',
            })
            const unmount = templater.mount()
            templater.actions.setEmailEditorRef({
                editor: {
                    registerProvider: jest.fn(),
                    registerCallback: jest.fn(),
                    loadDesign: jest.fn(),
                    addEventListener: (event: string, callback: () => void) => {
                        editorListeners[event] = callback
                    },
                    exportHtml: (callback: (data: any) => void) => {
                        const deliver = (): void =>
                            callback({ design: { body: { id: 'mine' } }, html: '<p>Canvas edit</p>' })
                        if (exportGate) {
                            void exportGate.then(deliver)
                        } else {
                            deliver()
                        }
                    },
                    exportPlainText: (callback: (data: any) => void) => callback({ text: 'Canvas edit' }),
                },
            } as any)
            templater.actions.onEmailEditorReady()
            return {
                emitDesignUpdated: () => editorListeners['design:updated'](),
                unmount,
            }
        }

        it('flushes pending canvas edits before adopting an external draft from a setting save', async () => {
            logic.unmount()
            const externalDraft = {
                templating: 'liquid' as const,
                email: { subject: 'From other tab', html: '<p>Other</p>' },
            }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': {
                        ...serverTemplate,
                        sensitive: true,
                        click_tracking_enabled: null,
                        updated_at: '2026-01-01T00:00:00Z',
                    },
                },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': async ({ request }) => {
                        const body = (await request.json()) as Record<string, unknown>
                        return [
                            200,
                            {
                                ...serverTemplate,
                                ...body,
                                sensitive: true,
                                draft_content: externalDraft,
                                updated_at: '2026-01-01T00:02:00Z',
                            },
                        ]
                    },
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const canvas = mountMockEmailTemplater(logic)
            canvas.emitDesignUpdated()

            logic.actions.setClickTrackingEnabled(true)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.externallyEdited).toBe(true)
            expect(logic.values.template.content.email.html).toBe('<p>Canvas edit</p>')
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
            canvas.unmount()
        })

        it('flushes pending canvas edits before syncing an older publish response without leaking autosave', async () => {
            logic.unmount()
            let releasePublish!: () => void
            const publishGate = new Promise<void>((resolve) => {
                releasePublish = resolve
            })
            let publishStarted!: () => void
            const publishArrived = new Promise<void>((resolve) => {
                publishStarted = resolve
            })
            let releaseExport!: () => void
            const exportGate = new Promise<void>((resolve) => {
                releaseExport = resolve
            })
            const newerServerDraft = {
                templating: 'liquid' as const,
                email: { subject: 'From other tab', html: '<p>Newer server draft</p>' },
            }
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                bodies.push(body)
                if ('click_tracking_enabled' in body) {
                    await publishArrived
                    currentServer = {
                        ...currentServer,
                        ...body,
                        draft_content: newerServerDraft,
                        updated_at: '2026-01-01T00:02:00Z',
                    }
                    return [200, { ...currentServer }]
                }
                if ('draft_content' in body) {
                    currentServer = { ...currentServer, ...body, updated_at: '2026-01-01T00:03:00Z' }
                    return [200, { ...currentServer }]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    draft_content: null,
                    updated_at: '2026-01-01T00:01:00Z',
                }
                const publishResponse = { ...currentServer }
                publishStarted()
                await publishGate
                return [200, publishResponse]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            const canvas = mountMockEmailTemplater(logic, exportGate)

            logic.actions.setClickTrackingEnabled(true)
            logic.actions.submitTemplate()
            await publishArrived
            await jest.advanceTimersByTimeAsync(10)
            expect(logic.values.isSavingClickTracking).toBe(false)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
            // Edit both the form and the canvas before the delayed publish response arrives.
            logic.actions.setTemplateValue('content.email.subject', 'Typed subject during publish')
            canvas.emitDesignUpdated()

            releasePublish()
            // Advance past the 1500ms autosave debounce while exportHtml is still pending.
            await jest.advanceTimersByTimeAsync(2000)
            expect(logic.values.isReconcilingPublish).toBe(true)
            logic.actions.submitTemplate()
            await jest.advanceTimersByTimeAsync(10)
            expect(bodies.filter((body) => 'content' in body)).toHaveLength(1)
            expect(currentServer.draft_content).toEqual(newerServerDraft)
            expect(bodies.some((body) => 'draft_content' in body)).toBe(false)

            releaseExport()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isReconcilingPublish).toBe(false)
            expect(logic.values.externallyEdited).toBe(true)
            expect(logic.values.template.content.email.html).toBe('<p>Canvas edit</p>')
            expect(bodies.filter((body) => 'content' in body)).toHaveLength(1)
            expect(currentServer.draft_content).toEqual(newerServerDraft)
            expect(bodies.some((body) => 'draft_content' in body)).toBe(false)
            canvas.unmount()
        })

        it('does not flag a false conflict when typing during publish after a newer own click tracking save', async () => {
            logic.unmount()
            let releasePublish!: () => void
            const publishGate = new Promise<void>((resolve) => {
                releasePublish = resolve
            })
            let publishStarted!: () => void
            const publishArrived = new Promise<void>((resolve) => {
                publishStarted = resolve
            })
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                bodies.push(body)
                if ('click_tracking_enabled' in body) {
                    await publishArrived
                    currentServer = {
                        ...currentServer,
                        ...body,
                        updated_at: '2026-01-01T00:02:00Z',
                    }
                    return [200, { ...currentServer }]
                }
                if ('draft_content' in body) {
                    currentServer = { ...currentServer, ...body, updated_at: '2026-01-01T00:03:00Z' }
                    return [200, { ...currentServer }]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    draft_content: null,
                    updated_at: '2026-01-01T00:01:00Z',
                }
                const publishResponse = { ...currentServer }
                publishStarted()
                await publishGate
                return [200, publishResponse]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            jest.useFakeTimers()

            logic.actions.setClickTrackingEnabled(true)
            logic.actions.submitTemplate()
            await publishArrived
            await jest.advanceTimersByTimeAsync(10)
            expect(logic.values.isSavingClickTracking).toBe(false)
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
            logic.actions.setTemplateValue('name', 'Typed during publish')

            releasePublish()
            await jest.advanceTimersByTimeAsync(2000)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.externallyEdited).toBe(false)
            expect(logic.values.template.name).toBe('Typed during publish')
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
        })

        it('reconciles when another editor reverts a published rename before an own click tracking save lands', async () => {
            logic.unmount()
            let releasePublish!: () => void
            const publishGate = new Promise<void>((resolve) => {
                releasePublish = resolve
            })
            let publishStarted!: () => void
            const publishArrived = new Promise<void>((resolve) => {
                publishStarted = resolve
            })
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                name: 'Original name',
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                if ('click_tracking_enabled' in body) {
                    await publishArrived
                    // Another tab restores the original name after publish committed at T1.
                    currentServer = {
                        ...currentServer,
                        ...body,
                        name: 'Original name',
                        updated_at: '2026-01-01T00:02:00Z',
                    }
                    return [200, { ...currentServer }]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    draft_content: null,
                    updated_at: '2026-01-01T00:01:00Z',
                }
                const publishResponse = { ...currentServer }
                publishStarted()
                await publishGate
                return [200, publishResponse]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setTemplateValue('name', 'Renamed in publish')
            logic.actions.setClickTrackingEnabled(true)
            logic.actions.submitTemplate()
            await publishArrived
            await waitFor(() => expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true))

            releasePublish()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.template.name).toBe('Original name')
            expect(logic.values.originalTemplate.click_tracking_enabled).toBe(true)
        })

        it('blocks direct publish and preserves an unsaved rename when an external edit arrives during discard', async () => {
            logic.unmount()
            let releaseDiscard!: () => void
            const discardGate = new Promise<void>((resolve) => {
                releaseDiscard = resolve
            })
            let discardStarted!: () => void
            const discardArrived = new Promise<void>((resolve) => {
                discardStarted = resolve
            })
            const renamedElsewhere = 'Renamed elsewhere'
            const patchBodies: Record<string, unknown>[] = []
            let currentServer: Record<string, unknown> = {
                ...serverTemplate,
                sensitive: true,
                click_tracking_enabled: null,
                updated_at: '2026-01-01T00:00:00Z',
            }
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                patchBodies.push(body)
                if ('draft_content' in body && body.draft_content === null) {
                    currentServer = {
                        ...currentServer,
                        draft_content: null,
                        updated_at: '2026-01-01T00:01:00Z',
                    }
                    const discardResponse = { ...currentServer }
                    discardStarted()
                    await discardGate
                    return [200, discardResponse]
                }
                currentServer = {
                    ...currentServer,
                    ...body,
                    updated_at: '2026-01-01T00:03:00Z',
                }
                return [200, { ...currentServer }]
            }
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [200, { ...currentServer }] },
                patch: {
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.confirmDiscardDraft()
            await discardArrived
            logic.actions.submitTemplate()
            expect(patchBodies).toEqual([{ draft_content: null }])

            currentServer = {
                ...currentServer,
                name: renamedElsewhere,
                updated_at: '2026-01-01T00:02:00Z',
            }
            resourceEditedLogic.actions.resourceEdited({
                notification_type: 'resource_edited',
                team_id: 1,
                resource_type: 'MessageTemplate',
                resource_id: 'existing-id',
                updated_at: '2026-01-01T00:02:00Z',
                actor_user_id: null,
            })
            logic.actions.setTemplateValue('name', 'Unsaved rename')

            releaseDiscard()
            await expectLogic(logic).toFinishAllListeners()

            expect(patchBodies).toEqual([{ draft_content: null }])
            expect(logic.values.template.name).toBe('Unsaved rename')
            expect(logic.values.externallyEdited).toBe(true)
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
