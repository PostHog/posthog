import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import { DEFAULT_BROADCAST_EMAIL, DELETED_SENDER_ERROR, broadcastWizardLogic } from './broadcastWizardLogic'

const LOCAL_AUDIENCE: AnyPropertyFilter[] = [
    { key: 'plan', value: ['pro'], operator: PropertyOperator.Exact, type: PropertyFilterType.Person },
]

function savedBroadcast(overrides: { name: string; subject: string; updatedAt: string }): HogFlowApi {
    return {
        id: 'broadcast-1',
        name: overrides.name,
        version: 1,
        status: 'draft',
        created_at: '2026-01-01T00:00:00Z',
        created_by: { id: 1, uuid: 'user-1', email: 'user@example.com', hedgehog_config: null },
        updated_at: overrides.updatedAt,
        last_run: null,
        trigger: { type: 'batch', filters: { properties: [] } },
        conversion: null,
        email_sending_rate_limit: null,
        actions: [
            {
                id: 'trigger_node',
                name: 'Trigger',
                type: 'trigger',
                config: { type: 'batch', filters: { properties: [] } },
            },
            {
                id: 'email_node',
                name: 'Email',
                type: 'function_email',
                config: { inputs: { email: { value: { subject: overrides.subject } } } },
            },
        ],
        abort_action: null,
        billable_action_types: [],
        schedules: [],
        user_access_level: 'editor',
        draft: null,
        draft_updated_at: null,
        action_redirects: null,
        email_sending_paused_at: null,
        email_sending_paused_reason: '',
        email_sending_paused_by: '',
        email_sending_pause_requires_support: false,
        email_sending_resumed_at: null,
    }
}

describe('broadcastWizardLogic', () => {
    let logic: ReturnType<typeof broadcastWizardLogic.build>
    let latest: HogFlowApi
    let releaseCreate: () => void
    let patchedSubjects: string[]
    let patchedTracking: unknown[]
    let patchedNames: string[]
    let holdPatch: Promise<void> | null
    let onPatchStarted: (() => void) | null
    let failPatches: number

    beforeEach(() => {
        patchedSubjects = []
        patchedTracking = []
        patchedNames = []
        holdPatch = null
        onPatchStarted = null
        failPatches = 0
        const created = new Promise<void>((resolve) => {
            releaseCreate = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/:id/': () => [200, latest],
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'email', config: { verified: true } }],
                    count: 1,
                },
            },
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
                '/api/projects/:team_id/hog_flows/': async () => {
                    await created
                    return [201, savedBroadcast({ name: '', subject: '', updatedAt: '2026-09-24T10:00:00Z' })]
                },
            },
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    const body = (await request.json()) as { actions?: any[]; name?: string }
                    if (!body.actions) {
                        patchedNames.push(body.name ?? '')
                        return [
                            200,
                            savedBroadcast({ name: body.name ?? '', subject: '', updatedAt: '2026-09-24T10:00:05Z' }),
                        ]
                    }
                    const emailConfig = body.actions.find((action) => action.type === 'function_email').config
                    const subject = emailConfig.inputs.email.value.subject
                    if (failPatches > 0) {
                        failPatches -= 1
                        return [500, { detail: 'Simulated outage' }]
                    }
                    patchedSubjects.push(subject)
                    patchedTracking.push(emailConfig.tracking_enabled)
                    onPatchStarted?.()
                    if (holdPatch) {
                        await holdPatch
                    }
                    return [200, savedBroadcast({ name: '', subject, updatedAt: '2026-09-24T10:00:05Z' })]
                },
            },
        })
        initKeaTests()
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        { edited: 'only the email', latestName: 'Spring sale', expectedName: 'Spring sale, final' },
        { edited: 'the name too', latestName: 'Spring promo', expectedName: 'Spring promo' },
    ])(
        'an edit saved elsewhere that changed $edited keeps the unsaved local fields it did not change',
        async ({ latestName, expectedName }) => {
            const base = savedBroadcast({ name: 'Spring sale', subject: '', updatedAt: '2026-09-24T10:00:00Z' })
            latest = savedBroadcast({
                name: latestName,
                subject: 'Our spring sale starts today',
                updatedAt: '2026-09-24T10:00:05Z',
            })
            logic.actions.draftAutosaved(base)
            logic.actions.setName('Spring sale, final')
            logic.actions.setAudienceProperties(LOCAL_AUDIENCE)

            await expectLogic(logic, () => {
                logic.actions.resourceEdited({
                    notification_type: 'resource_edited',
                    team_id: 1,
                    resource_type: 'HogFlow',
                    resource_id: base.id,
                    updated_at: latest.updated_at,
                    actor_user_id: null,
                })
            })
                .toDispatchActions(['applyExternalEdit'])
                .toMatchValues({
                    broadcast: latest,
                    name: expectedName,
                    audienceProperties: LOCAL_AUDIENCE,
                    email: expect.objectContaining({ subject: 'Our spring sale starts today' }),
                })
        }
    )

    it.each([
        { case: 'a renamed draft', status: 'draft', name: 'Spring sale, final', saved: ['Spring sale, final'] },
        { case: 'an unchanged name', status: 'draft', name: 'Spring sale', saved: [] },
        { case: 'a blank name', status: 'draft', name: '  ', saved: [] },
        { case: 'a live broadcast', status: 'active', name: 'Spring sale, final', saved: [] },
    ])('saves the name on blur only for $case', async ({ status, name, saved }) => {
        logic.actions.draftAutosaved({
            ...savedBroadcast({ name: 'Spring sale', subject: '', updatedAt: '2026-09-24T10:00:00Z' }),
            status: status as HogFlowApi['status'],
        })
        logic.actions.setName(name)

        await expectLogic(logic, () => {
            logic.actions.saveName()
        }).toFinishAllListeners()

        expect(patchedNames).toEqual(saved)
        if (saved.length) {
            expect(logic.values.broadcast?.name).toEqual(name)
        }
    })

    it('moves a new broadcast onto its draft URL once the draft is created', async () => {
        router.actions.push('/broadcasts/new')
        await expectLogic(logic, () => {
            logic.actions.setStep('content')
            releaseCreate()
        }).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])

        expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
        expect(router.values.searchParams).toEqual({ step: 'content' })
    })

    it.each([
        {
            edit: 'an email edit',
            apply: (): void =>
                logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, subject: 'Typed during the create' }),
            subject: 'Typed during the create',
            tracking: true,
        },
        {
            edit: 'turning tracking off',
            apply: (): void => logic.actions.setEmailSettings({ trackingEnabled: false }),
            subject: '',
            tracking: false,
        },
    ])('saves $edit made while the draft is created before leaving /broadcasts/new', async (testCase) => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        testCase.apply()
        releaseCreate()

        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'draftAutosaved'])
        await expectLogic(logic).toDispatchActions(['showSavedDraftUrl']).toFinishAllListeners()

        expect(patchedSubjects).toEqual([testCase.subject])
        expect(patchedTracking).toEqual([testCase.tracking])
        expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
    })

    it('retries a failed email autosave and moves to the draft URL once it saves', async () => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])
        router.actions.push('/broadcasts/new')
        failPatches = 1

        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, subject: 'Saved on the retry' })

        await expectLogic(logic)
            .toDispatchActions(['setEmail', 'draftAutosaved', 'showSavedDraftUrl'])
            .toFinishAllListeners()
        expect(patchedSubjects).toEqual(['Saved on the retry'])
        expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
    })

    it('moves to the draft URL when Continue saves an email edit still waiting on its autosave', async () => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])
        router.actions.push('/broadcasts/new')

        logic.actions.setEmail({
            ...DEFAULT_BROADCAST_EMAIL,
            from: { ...DEFAULT_BROADCAST_EMAIL.from, integrationId: 1 },
            subject: 'Typed before Continue',
            html: '<p>Hi</p>',
        })
        await expectLogic(logic, () => {
            logic.actions.continueStep()
        }).toDispatchActions(['nextStep', 'showSavedDraftUrl'])

        expect(patchedSubjects).toEqual(['Typed before Continue'])
        expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
    })

    it('keeps an email edit made while Continue is saving and moves to the draft URL after it saves', async () => {
        const validEmail = {
            ...DEFAULT_BROADCAST_EMAIL,
            from: { ...DEFAULT_BROADCAST_EMAIL.from, integrationId: 1 },
            html: '<p>Hi</p>',
        }
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved'])
        logic.actions.setEmail({ ...validEmail, subject: 'Saved by Continue' })
        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])
        router.actions.push('/broadcasts/new')
        patchedSubjects = []

        let releasePatch: () => void = () => {}
        holdPatch = new Promise((resolve) => {
            releasePatch = resolve
        })
        const patchStarted = new Promise<void>((resolve) => {
            onPatchStarted = resolve
        })
        logic.actions.continueStep()
        await patchStarted
        holdPatch = null
        logic.actions.setEmail({ ...validEmail, subject: 'Typed during Continue' })
        releasePatch()

        await expectLogic(logic).toDispatchActions(['nextStep', 'draftAutosaved', 'showSavedDraftUrl'])
        expect(patchedSubjects).toEqual(['Saved by Continue', 'Typed during Continue'])
        expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
    })

    it.each([
        { stop: 'the audience is over the batch limit', affected: 60000, editedElsewhere: false, step: 'recipients' },
        { stop: 'the draft was edited elsewhere', affected: 10, editedElsewhere: true, step: 'review' },
    ])(
        'moves to the draft URL when a launch from /broadcasts/new stops because $stop',
        async ({ affected, editedElsewhere, step }) => {
            latest = savedBroadcast({
                name: '',
                subject: 'Edited by the assistant',
                updatedAt: editedElsewhere ? '2026-09-24T10:00:09Z' : '2026-09-24T10:00:00Z',
            })
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [
                        200,
                        { affected, total: affected, limit: 50000, dedupe_key: 'email', confirm_token: 'token' },
                    ],
                },
            })
            router.actions.push('/broadcasts/new')
            logic.actions.setEmail({
                ...DEFAULT_BROADCAST_EMAIL,
                from: { ...DEFAULT_BROADCAST_EMAIL.from, integrationId: 1 },
                subject: 'Launch over the limit',
                html: '<p>Hi</p>',
            })
            releaseCreate()

            logic.actions.setStep('review')
            await expectLogic(logic, () => {
                logic.actions.launchBroadcast()
            }).toDispatchActions(['saveBroadcastFinished', 'launchBroadcastFinished', 'showSavedDraftUrl'])

            expect(router.values.location.pathname).toContain('/broadcasts/broadcast-1')
            expect(router.values.searchParams).toEqual({ step })
        }
    )

    it.each([
        { sender: 'a sender that still exists', integrationId: 1, integrationIds: undefined, expected: [] },
        { sender: 'a deleted sender', integrationId: 7, integrationIds: undefined, expected: [DELETED_SENDER_ERROR] },
        {
            sender: 'a deleted sender in the rotation',
            integrationId: 1,
            integrationIds: [1, 7],
            expected: [DELETED_SENDER_ERROR],
        },
    ])('flags $sender on the content step and once on review', async ({ integrationId, integrationIds, expected }) => {
        integrationsLogic.mount()
        await expectLogic(integrationsLogic, () => {
            integrationsLogic.actions.loadIntegrations()
        }).toDispatchActions(['loadIntegrationsSuccess'])

        logic.actions.setEmail({
            ...DEFAULT_BROADCAST_EMAIL,
            from: { ...DEFAULT_BROADCAST_EMAIL.from, integrationId, integrationIds },
            subject: 'Spring sale',
            html: '<p>Hi</p>',
        })

        expect(logic.values.stepValidationErrors.content).toEqual(expected)
        expect(logic.values.stepValidationErrors.review).toEqual(expected)
    })

    it('resumes a saved draft on the step in its URL and drops the step from the URL', async () => {
        latest = savedBroadcast({ name: 'Spring sale', subject: '', updatedAt: '2026-09-24T10:00:00Z' })
        router.actions.push('/broadcasts/broadcast-1', { step: 'content', other: 'kept' })
        const draftLogic = broadcastWizardLogic({ id: 'broadcast-1' })

        await expectLogic(draftLogic, () => {
            draftLogic.mount()
        })
            .toDispatchActions(['hydrateFromBroadcast', 'setStep'])
            .toMatchValues({ currentStep: 'content' })
        expect(router.values.searchParams).toEqual({ other: 'kept' })
        draftLogic.unmount()
    })
})
