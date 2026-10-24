import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

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

        beforeEach(async () => {
            patchBodies = []
            createBodies = []
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
        })
    })

    describe('claimed back by an upload while editing', () => {
        const draft = { ...CODE_MANAGED.content, email: { ...CODE_MANAGED.content.email, subject: 'Draft subject' } }
        const claimed = { ...CODE_MANAGED, transactional_hog_flow_id: 'flow-id', draft_content: null }
        let serverTemplate: Record<string, unknown>
        let reloadStatus: number
        let createBodies: Record<string, unknown>[]

        const editTemplate = (): void => {
            logic.actions.setTemplateValue('name', 'Welcome, edited here')
            logic.actions.setTemplateValue('content.email.subject', 'Edited subject')
        }

        const autosave = async (): Promise<void> => {
            await jest.advanceTimersByTimeAsync(1500)
        }

        const autosaveThenClaim = async (): Promise<void> => {
            await autosave()
            await expectLogic(logic).toDispatchActions(['saveDraftDone'])
            serverTemplate = claimed
        }

        const publish = async (): Promise<void> => {
            await autosaveThenClaim()
            logic.actions.submitTemplate()
        }

        const discardDraft = async (): Promise<void> => {
            await autosaveThenClaim()
            logic.actions.confirmDiscardDraft()
        }

        const claimThenAutosave = async (): Promise<void> => {
            serverTemplate = claimed
            await autosave()
        }

        const refuse = async (refusal: () => Promise<void>): Promise<void> => {
            editTemplate()
            await refusal()
            await jest.advanceTimersByTimeAsync(3000)
            await expectLogic(logic).toDispatchActions([
                reloadStatus === 200 ? 'loadTemplateSuccess' : 'loadTemplateFailure',
            ])
        }

        beforeEach(async () => {
            serverTemplate = { ...claimed, managed_by: 'gui', draft_content: draft }
            reloadStatus = 200
            createBodies = []
            const patch = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
                const body = (await request.json()) as Record<string, unknown>
                if (serverTemplate.managed_by === 'code') {
                    return [
                        403,
                        { type: 'invalid_request', code: 'immutable', detail: 'This template is managed by code.' },
                    ]
                }
                return [200, { ...serverTemplate, ...body, updated_at: '2026-01-01T00:01:00Z' }]
            }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [reloadStatus, serverTemplate],
                },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': patch,
                    '/api/projects/:team_id/messaging_templates/:id/': patch,
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
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        const keptEdits = expect.objectContaining({ name: 'Welcome, edited here' })

        it.each([
            { refusal: 'an autosave', refuse: claimThenAutosave, reload: 'succeeds', status: 200, edits: keptEdits },
            { refusal: 'an autosave', refuse: claimThenAutosave, reload: 'fails', status: 500, edits: keptEdits },
            { refusal: 'a publish', refuse: publish, reload: 'succeeds', status: 200, edits: keptEdits },
            { refusal: 'a publish', refuse: publish, reload: 'fails', status: 500, edits: keptEdits },
            { refusal: 'a draft discard', refuse: discardDraft, reload: 'fails', status: 500, edits: null },
        ])(
            'turns read-only when $refusal is refused and the reload $reload',
            async ({ refuse: refusal, status, edits }) => {
                reloadStatus = status
                await refuse(refusal)

                await expectLogic(logic).toMatchValues({
                    isCodeManaged: true,
                    hasDraft: false,
                    hasUnsavedChanges: false,
                    refusedEdits: edits,
                })
                expect(logic.values.template.name).toBe('Welcome')
            }
        )

        it.each([
            {
                requests: 'an autosave and a publish',
                refuse: async (): Promise<void> => {
                    serverTemplate = claimed
                    logic.actions.saveDraft()
                    logic.actions.submitTemplate()
                },
            },
            {
                requests: 'an autosave, then a draft discard',
                refuse: async (): Promise<void> => {
                    await claimThenAutosave()
                    logic.actions.confirmDiscardDraft()
                },
            },
        ])('keeps the edits the first refusal rescued when $requests are refused', async ({ refuse: refusal }) => {
            await refuse(refusal)
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ isCodeManaged: true, refusedEdits: keptEdits })
        })

        it('keeps the edits from before and after a release when a second upload refuses them', async () => {
            await refuse(claimThenAutosave)
            serverTemplate = { ...claimed, managed_by: 'gui' }
            await expectLogic(logic, () => {
                logic.actions.releaseTemplate()
            }).toDispatchActions(['releaseTemplateSuccess'])
            await expectLogic(logic).toMatchValues({ refusedEdits: null, hasUnsavedChanges: true })

            logic.actions.setTemplateValue('description', 'Edited after the release')
            await claimThenAutosave()
            await expectLogic(logic).toDispatchActions(['claimedByUpload']).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                isCodeManaged: true,
                refusedEdits: expect.objectContaining({
                    name: 'Welcome, edited here',
                    description: 'Edited after the release',
                }),
            })
        })

        it('asks before a navigation drops the refused edits', async () => {
            const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(false)
            await refuse(claimThenAutosave)

            router.actions.push('/workflows/library')

            expect(confirmSpy).toHaveBeenCalledTimes(1)
            confirmSpy.mockRestore()
        })

        it('duplicates the unsaved edits without its key, ownership, source or hash', async () => {
            await refuse(claimThenAutosave)

            await expectLogic(logic, () => {
                logic.actions.duplicateWithMyChanges()
            }).toFinishAllListeners()

            expect(createBodies).toEqual([
                {
                    name: 'Welcome, edited here (copy)',
                    description: 'Sent after signup',
                    content: { ...draft, email: { ...draft.email, subject: 'Edited subject' } },
                },
            ])
            await expectLogic(logic).toMatchValues({ refusedEdits: null })
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
})
