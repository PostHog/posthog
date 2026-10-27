import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { BlastRadiusApi, HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import { draftMessage } from '../MessageAudience/messageDrafts'
import { urlForNewBroadcastWithAudience } from './broadcastAudiencePrefill'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
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
        tags: [],
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
                '/api/projects/:team_id/hog_flows/new/invocations/': () => [
                    200,
                    { status: 'success', nextActionId: null, logs: [] },
                ],
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

    it('remembers a delivered test, for the address it went to, until the email changes', async () => {
        const testSend = broadcastTestSendLogic({ id: 'new' })
        testSend.mount()
        // Let the wizard fill its default sender first, which is an email change of its own.
        await expectLogic(logic).toFinishAllListeners()
        const sendTest = async (): Promise<void> => {
            testSend.actions.setRecipientEmail('reviewer@example.com')
            testSend.actions.sendTestEmail()
            // Edited while the send runs, which must not change who the card says got it.
            testSend.actions.setRecipientEmail('typo@example.com')
            await expectLogic(testSend).toDispatchActions(['sendTestEmailSuccess']).toFinishAllListeners()
        }

        await sendTest()
        expect(testSend.values.lastTestSentTo).toBe('reviewer@example.com')
        logic.actions.setEmail({ ...logic.values.email, subject: 'Changed after the test' })
        expect(testSend.values.lastTestSentTo).toBeNull()

        await sendTest()
        logic.actions.applyExternalEdit(
            savedBroadcast({ name: '', subject: 'Rewritten by the assistant', updatedAt: '2026-09-24T10:00:09Z' }),
            null
        )
        expect(testSend.values.lastTestSentTo).toBeNull()
        testSend.unmount()
    })

    it('prefills the audience, name and source from a link without creating a draft', async () => {
        const properties: AnyPropertyFilter[] = [
            { key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In },
        ]
        logic.unmount()
        router.actions.push(urlForNewBroadcastWithAudience({ properties, name: 'Fix shipped', source: 'cohort' }))
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['prefillFromLink', 'loadBlastRadius'])
            .toNotHaveDispatchedActions(['ensureDraft'])
        expect(logic.values.audienceProperties).toEqual(properties)
        expect(logic.values.name).toEqual('Fix shipped')
        expect(logic.values.entrySource).toEqual('cohort')

        // A reload remounts the wizard from the same URL, and nothing was saved yet.
        logic.unmount()
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['prefillFromLink'])
        expect(logic.values.audienceProperties).toEqual(properties)
        expect(logic.values.name).toEqual('Fix shipped')
    })

    it.each([
        {
            link: 'a draft email and one verified sender',
            email: draftMessage({ kind: 'issue_fixed' }),
            verified: true,
            step: 'review',
        },
        {
            link: 'a draft email but no verified sender',
            email: draftMessage({ kind: 'issue_fixed' }),
            verified: false,
            step: 'content',
        },
        { link: 'no email', email: undefined, verified: true, step: 'content' },
    ])('opens a link with $link on the $step step without creating a draft', async ({ email, verified, step }) => {
        const createDraft = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'email', config: { verified } }],
                    count: 1,
                },
            },
            post: { '/api/projects/:team_id/hog_flows/': () => createDraft() },
        })
        logic.unmount()
        router.actions.push(
            urlForNewBroadcastWithAudience({ properties: LOCAL_AUDIENCE, source: 'error_tracking', email })
        )
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()
        integrationsLogic.mount()

        await expectLogic(logic, () => {
            integrationsLogic.actions.loadIntegrations()
        }).toDispatchActions(['landOnStep'])

        expect(logic.values.currentStep).toEqual(step)
        expect(logic.values.email.subject).toEqual(email?.subject ?? '')
        expect(createDraft).not.toHaveBeenCalled()
    })

    it.each([
        { case: 'untouched', edit: null, fallback: null, subject: 'Written by the model', status: 'applied' },
        {
            case: 'edited while it loads',
            edit: 'Typed by the person',
            fallback: null,
            subject: 'Typed by the person',
            status: null,
        },
        { case: 'rate limited', edit: null, fallback: 'rate_limited', subject: null, status: 'failed' },
    ])(
        'replaces the link email with the AI draft only when it is $case',
        async ({ edit, fallback, subject, status }) => {
            let respond: (value: unknown) => void = () => {}
            useMocks({
                post: {
                    '/api/projects/:team_id/workflow_email_drafts/': () =>
                        new Promise((resolve) => {
                            respond = resolve
                        }).then((body) => [200, body]),
                },
            })
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AI_EMAIL_DRAFT]: true })
            logic.unmount()
            router.actions.push(
                urlForNewBroadcastWithAudience({
                    properties: LOCAL_AUDIENCE,
                    source: 'error_tracking',
                    name: 'We fixed it',
                    email: draftMessage({ kind: 'issue_fixed' }),
                    draftSource: { source: 'error_tracking', source_id: 'issue-1' },
                })
            )
            logic = broadcastWizardLogic({ id: 'new' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadAiEmailDraft'])
            expect(logic.values.aiEmailDraftLoading).toBe(true)
            if (edit) {
                logic.actions.setEmail({ ...logic.values.email, subject: edit })
            }
            respond({
                subject: 'Written by the model',
                preheader: '',
                html: '<p>Hi there,</p>\n<p>Second paragraph.</p>',
                text: 'Hi there,\n\nSecond paragraph.',
                generated_by: fallback ? 'template' : 'ai',
                template_reason: fallback,
            })
            await expectLogic(logic).toDispatchActions(['loadAiEmailDraftSuccess'])

            const applied = status === 'applied'
            const template = draftMessage({ kind: 'issue_fixed' })
            expect(logic.values.aiEmailDraftStatus?.status ?? null).toEqual(status)
            expect(logic.values.email.subject).toEqual(subject ?? template.subject)
            expect(logic.values.email.text).toEqual(
                applied ? 'Hi there,\n\nSecond paragraph.' : template.paragraphs.join('\n\n')
            )
            // The name was the link's, so it follows the AI subject and stays put otherwise.
            expect(logic.values.name).toEqual(applied ? 'Written by the model' : 'We fixed it')
        }
    )

    it('blocks the recipients step until the person chooses, when a link has an audience it cannot use', async () => {
        logic.unmount()
        router.actions.push(
            `/broadcasts/new?audience=${encodeURIComponent('[{"key":"email","type":"person","operator":"exact"}]')}&name=Fix%20shipped`
        )
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['rejectLinkAudience']).toNotHaveDispatchedActions(['ensureDraft'])
        expect(logic.values.name).toEqual('Fix shipped')
        expect(logic.values.stepValidationErrors.recipients).toEqual(['Choose who gets this email'])

        logic.actions.setAudienceProperties([
            { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsSet },
        ])
        expect(logic.values.stepValidationErrors.recipients).toEqual([])
        logic.actions.setAudienceProperties([])
        expect(logic.values.stepValidationErrors.recipients).toEqual(['Choose who gets this email'])

        logic.actions.sendToEveryoneAfterRejectedLink()
        expect(logic.values.stepValidationErrors.recipients).toEqual([])
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

    it.each([
        { case: 'untouched settings', edit: false, enabled: true, params: { utm_source: 'newsletter' } },
        { case: 'settings the user changed', edit: true, enabled: false, params: {} },
    ])('seeds team UTM defaults when the team loads after mount, for $case', ({ edit, enabled, params }) => {
        logic.unmount()
        teamLogic.actions.loadCurrentTeamSuccess(null)
        logic = broadcastWizardLogic({ id: 'new' })
        logic.mount()
        if (edit) {
            logic.actions.setEmailSettings({ trackingEnabled: false })
        }

        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                capture_workflows_engagement_events: false,
                email_utm_tags_enabled: true,
                email_utm_params: { utm_source: 'newsletter' },
            },
        })

        expect(logic.values.emailSettings).toMatchObject({ utmTagsEnabled: enabled, utmParams: params })
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

    it('autosaves a subject edited in place on the review step', async () => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved']).toFinishAllListeners()

        logic.actions.setStep('review')
        logic.actions.setEmail({ ...logic.values.email, subject: 'Edited on the review step' })
        await expectLogic(logic).toDispatchActions(['draftAutosaved']).toFinishAllListeners()

        expect(patchedSubjects.at(-1)).toBe('Edited on the review step')
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

    it('saves an email edit still waiting on its autosave before opening the workflow editor', async () => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])

        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, subject: 'Typed before the handoff' })
        const capture = jest.spyOn(posthog, 'capture')
        await expectLogic(logic, () => {
            logic.actions.openInWorkflowEditorConfirmed()
        })
            .toDispatchActions(['saveBroadcastFinished'])
            .toFinishAllListeners()

        expect(patchedSubjects.at(-1)).toEqual('Typed before the handoff')
        expect(router.values.location.pathname).toContain('/workflows/broadcast-1/workflow')
        expect(capture).toHaveBeenCalledWith('broadcast opened in workflow editor', {
            broadcast_id: 'broadcast-1',
            step: 'content',
        })
    })

    it('saves an email edit made while the workflow editor handoff is saving before it opens the editor', async () => {
        router.actions.push('/broadcasts/new')
        logic.actions.setStep('content')
        releaseCreate()
        await expectLogic(logic).toDispatchActions(['draftAutosaved', 'showSavedDraftUrl'])
        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, subject: 'Saved by the handoff' })

        let releasePatch: () => void = () => {}
        holdPatch = new Promise((resolve) => {
            releasePatch = resolve
        })
        const patchStarted = new Promise<void>((resolve) => {
            onPatchStarted = resolve
        })
        logic.actions.openInWorkflowEditorConfirmed()
        await patchStarted
        holdPatch = null
        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, subject: 'Typed during the handoff' })
        releasePatch()

        await expectLogic(logic).toDispatchActions(['saveBroadcastFinished']).toFinishAllListeners()
        expect(patchedSubjects.at(-1)).toEqual('Typed during the handoff')
        expect(router.values.location.pathname).toContain('/workflows/broadcast-1/workflow')
    })

    it('creates the draft and stores its send time when the workflow editor opens before any Continue', async () => {
        const createdSchedules: Record<string, any>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/:id/schedules/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    createdSchedules.push(body)
                    return [201, { id: 'schedule-1', ...body }]
                },
            },
        })
        const sendAt = dayjs().add(1, 'day').startOf('minute').toISOString()
        router.actions.push('/broadcasts/new')
        logic.actions.setScheduleMode('later')
        logic.actions.setSendAt(sendAt)
        logic.actions.setStep('review')
        releaseCreate()

        await expectLogic(logic, () => {
            logic.actions.openInWorkflowEditorConfirmed()
        })
            .toDispatchActions(['saveBroadcastFinished'])
            .toFinishAllListeners()

        expect(createdSchedules).toEqual([expect.objectContaining({ starts_at: sendAt, rrule: expect.any(String) })])
        expect(router.values.location.pathname).toContain('/workflows/broadcast-1/workflow')
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

    it('refreshes the realtime cohort status until the cohort is ready, past a failed check', async () => {
        const states = ['needs_attention', 'error', 'ready']
        let calls = 0
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': async ({ request }) => {
                    // The recipient email check posts here too, with an extra condition.
                    const { filters } = (await request.json()) as { filters: { properties: unknown[] } }
                    if (filters.properties.length > 1) {
                        return [200, { affected: 0, total: 0 }]
                    }
                    const state = states[Math.min(calls++, states.length - 1)]
                    if (state === 'error') {
                        return [500, { detail: 'Simulated outage' }]
                    }
                    return [
                        200,
                        {
                            affected: 0,
                            total: 0,
                            realtime_cohort: { id: 42, name: 'Upgraded', state, percent_complete: null },
                        },
                    ]
                },
            },
        })
        const statusLoaded =
            (state: string) =>
            (action: { type: string; payload?: { blastRadius?: BlastRadiusApi | null } }): boolean =>
                action.type === logic.actionTypes.loadBlastRadiusSuccess &&
                action.payload?.blastRadius?.realtime_cohort?.state === state
        await expectLogic(logic, () => {
            logic.actions.setAudienceProperties([
                { type: PropertyFilterType.Cohort, key: 'id', value: 42, operator: PropertyOperator.In },
            ])
        }).toDispatchActions([statusLoaded('needs_attention')])

        jest.useFakeTimers()
        try {
            await jest.advanceTimersByTimeAsync(20000)
            await expectLogic(logic).toDispatchActions([statusLoaded('ready')])
            expect(logic.values.blastRadius?.realtime_cohort?.state).toEqual('ready')

            await jest.advanceTimersByTimeAsync(30000)
            expect(calls).toEqual(3)
        } finally {
            jest.useRealTimers()
        }
    })

    const dynamicCohort = { id: 42, name: 'Upgraded', is_static: false, is_calculating: true }
    it.each([
        [
            'an uploaded list that is still matching',
            { id: 42, name: 'Spring list', is_static: true, is_calculating: true },
            null,
            ['"Spring list" is still matching people. You can launch when it finishes.'],
        ],
        [
            'a cohort before its first calculation',
            dynamicCohort,
            null,
            [`"Upgraded" is still calculating who's in it. You can launch when it finishes.`],
        ],
        [
            'a realtime cohort the send waits for',
            dynamicCohort,
            { id: 42, name: 'Upgraded', state: 'building', percent_complete: null },
            [],
        ],
    ])('checks the audience cohorts at launch: %s', async (_desc, cohort, realtimeCohort, expectedErrors) => {
        useMocks({
            get: { '/api/projects/:team_id/cohorts/:id/': cohort },
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [
                    200,
                    { affected: 0, total: 0, realtime_cohort: realtimeCohort },
                ],
            },
        })
        logic.actions.setEmail({
            ...DEFAULT_BROADCAST_EMAIL,
            from: { ...DEFAULT_BROADCAST_EMAIL.from, integrationId: 1 },
            subject: 'Spring sale',
            html: '<p>Hi</p>',
        })
        logic.actions.setAudienceProperties([
            { type: PropertyFilterType.Cohort, key: 'id', value: 42, operator: PropertyOperator.In },
        ])
        await expectLogic(logic, () => {
            logic.actions.loadBlastRadius()
        }).toDispatchActions(['loadBlastRadiusSuccess'])
        logic.actions.setStep('review')

        await expectLogic(logic, () => {
            logic.actions.launchBroadcast()
        }).toDispatchActions(['setAudienceCohortLaunchErrors'])

        expect(logic.values.stepValidationErrors.review).toEqual(expectedErrors)
    })

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

    it('counts the audience missing the To field property on the review step only, and never for an unfiltered audience', async () => {
        const missingByProperty: Record<string, number> = { email: 98, $email: 0 }
        const checkedFilters: { key: string; operator?: string }[][] = []
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/user_blast_radius/': async ({ request }) => {
                    const { filters } = (await request.json()) as {
                        filters: { properties: { key: string; operator?: string }[] }
                    }
                    const last = filters.properties[filters.properties.length - 1]
                    if (!last || last.operator !== PropertyOperator.IsNotSet) {
                        return [200, { affected: 98, total: 1000 }]
                    }
                    checkedFilters.push(filters.properties)
                    return [200, { affected: missingByProperty[last.key], total: 1000 }]
                },
            },
        })
        logic.actions.setAudienceProperties(LOCAL_AUDIENCE)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ recipientsWithoutEmail: null })
        expect(checkedFilters).toEqual([])

        logic.actions.setStep('review')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ recipientsWithoutEmail: 98 })
        expect(checkedFilters.at(-1)).toEqual([
            ...LOCAL_AUDIENCE,
            { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet },
        ])

        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, to: { email: '{{ person.properties.$email }}' } })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ recipientsWithoutEmail: 0 })

        logic.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, to: { email: 'team@example.com' } })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ recipientsWithoutEmail: null })

        const requestsBefore = checkedFilters.length
        logic.actions.setEmail(DEFAULT_BROADCAST_EMAIL)
        logic.actions.setAudienceProperties([])
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ recipientsWithoutEmail: null })
        expect(checkedFilters).toHaveLength(requestsBefore)
    })

    it('starts a new broadcast with the only verified sender without creating a draft', async () => {
        const createDraft = jest.fn()
        useMocks({ post: { '/api/projects/:team_id/hog_flows/': () => createDraft() } })
        integrationsLogic.mount()

        await expectLogic(logic, () => {
            integrationsLogic.actions.loadIntegrations()
        }).toDispatchActions(['defaultSenderApplied'])

        expect(logic.values.email.from).toEqual({ integrationId: 1 })
        expect(logic.values.stepValidationErrors.content).not.toContain('Choose an email sender')
        expect(createDraft).not.toHaveBeenCalled()
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
