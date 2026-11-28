import '@testing-library/jest-dom'

import userEvent, { PointerEventsCheckLevel } from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import type { MockResolverInfo } from '~/mocks/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureType,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import type { MessageAudience, MessageAudienceDestination } from './messageAudience'

jest.unmock('posthog-js')

const INGESTION_HOST = 'https://ingest.example.com'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TEST_SENDER_FOR_WORKFLOW =
    "You don't have a verified email sender yet. You can send a test from the PostHog test sender to verified members of your organization. To email your users, set up your own domain."
const NO_SENDER = 'Set up an email sender before sending'

type SentEvent = { event: string; properties: Record<string, any> }

const verified = { id: 1, kind: 'email', config: { verified: true } }
const testSender = {
    integration_id: 12,
    from_address: 'test@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const readyList = {
    id: 7,
    name: 'Signups',
    is_static: true,
    is_calculating: false,
    last_calculation: null,
    errors_calculating: 0,
    deleted: false,
    filters: { properties: { type: 'AND', values: [] } },
}
const flagCohort = { id: 42, name: 'Users with feature flag test-flag enabled', errors_calculating: 0 }
const SURVEY_ID = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a6c'
const CREATED_ID = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a7d'
const survey = {
    id: SURVEY_ID,
    name: 'Saved survey',
    description: '',
    type: SurveyType.Popover,
    questions: [{ type: SurveyQuestionType.Open, question: 'What do you think?', description: '' }],
    start_date: '2026-01-01T00:00:00Z',
    end_date: null,
    archived: false,
} as unknown as Survey
const earlyAccessFeature = {
    id: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
    name: 'Dark mode',
    description: 'A darker theme',
    stage: EarlyAccessFeatureStage.Beta,
    feature_flag: { id: 1, key: 'dark-mode' },
} as EarlyAccessFeatureType

describe('message audience attempts', () => {
    const sentEvents: SentEvent[] = []
    const createRequests: Record<string, unknown>[] = []
    let app: {
        rtl: typeof import('@testing-library/react/pure')
        router: typeof import('kea-router').router
        combineUrl: typeof import('kea-router').combineUrl
        initKeaTests: typeof import('~/test/init').initKeaTests
        ApiConfig: typeof import('lib/api').ApiConfig
        urls: typeof import('scenes/urls').urls
        toastify: { ToastContainer: () => JSX.Element; toast: { dismiss: () => void } }
        cohortSavedToast: typeof import('scenes/cohorts/cohortSavedToast').cohortSavedToast
        CohortEdit: typeof import('scenes/cohorts/CohortEdit').CohortEdit
        sceneLayoutLogic: typeof import('~/layout/scenes/sceneLayoutLogic').sceneLayoutLogic
        appFeatureFlagLogic: typeof import('lib/logic/featureFlagLogic').featureFlagLogic
        FEATURE_FLAGS: typeof import('lib/constants').FEATURE_FLAGS
        earlyAccessFeatureLogic: typeof import('products/early_access_features/frontend/earlyAccessFeatureLogic').earlyAccessFeatureLogic
        featureFlagLogic: typeof import('scenes/feature-flags/featureFlagLogic').featureFlagLogic
        NEW_FLAG: typeof import('scenes/feature-flags/featureFlagLogic').NEW_FLAG
        surveyLogic: typeof import('scenes/surveys/surveyLogic').surveyLogic
        SurveyFollowUpWorkflowButton: typeof import('scenes/surveys/components/SurveyFollowUpWorkflowButton').SurveyFollowUpWorkflowButton
        openIssueWorkflow: typeof import('products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/issueWorkflow').openIssueWorkflow
        surveyRespondentsBroadcastLogic: typeof import('scenes/surveys/components/surveyRespondentsBroadcastLogic').surveyRespondentsBroadcastLogic
        enrolledPeopleAudience: typeof import('products/early_access_features/frontend/enrolledPeopleAudience').enrolledPeopleAudience
        BroadcastScene: typeof import('../Broadcasts/BroadcastScene').BroadcastScene
        urlForNewBroadcastWithAudience: typeof import('../Broadcasts/broadcastAudiencePrefill').urlForNewBroadcastWithAudience
        WorkflowScene: typeof import('../Workflows/WorkflowScene').WorkflowScene
        urlForNewWorkflowWithTrigger: typeof import('../Workflows/workflowTriggerPrefill').urlForNewWorkflowWithTrigger
        ATTEMPT_PREFILL_PARAM: typeof import('./messageAudienceAttempts').ATTEMPT_PREFILL_PARAM
        MessageAudienceButton: typeof import('./MessageAudienceButton').MessageAudienceButton
    }

    beforeAll(async () => {
        jest.resetModules()
        const posthog = (await import('posthog-js')).default
        posthog.init('phc_example', {
            api_host: INGESTION_HOST,
            persistence: 'memory',
            request_batching: false,
            disable_compression: true,
            advanced_disable_flags: true,
            autocapture: false,
            capture_pageview: false,
            rate_limiting: { events_per_second: 1000, events_burst_limit: 10_000 },
        })
        const { initKeaTests } = await import('~/test/init')
        initKeaTests()
        const featureFlags = await import('scenes/feature-flags/featureFlagLogic')
        app = {
            rtl: await import('@testing-library/react/pure'),
            router: (await import('kea-router')).router,
            combineUrl: (await import('kea-router')).combineUrl,
            initKeaTests,
            ApiConfig: (await import('lib/api')).ApiConfig,
            urls: (await import('scenes/urls')).urls,
            toastify: jest.requireActual('react-toastify'),
            cohortSavedToast: (await import('scenes/cohorts/cohortSavedToast')).cohortSavedToast,
            CohortEdit: (await import('scenes/cohorts/CohortEdit')).CohortEdit,
            sceneLayoutLogic: (await import('~/layout/scenes/sceneLayoutLogic')).sceneLayoutLogic,
            appFeatureFlagLogic: (await import('lib/logic/featureFlagLogic')).featureFlagLogic,
            FEATURE_FLAGS: (await import('lib/constants')).FEATURE_FLAGS,
            earlyAccessFeatureLogic: (await import('products/early_access_features/frontend/earlyAccessFeatureLogic'))
                .earlyAccessFeatureLogic,
            featureFlagLogic: featureFlags.featureFlagLogic,
            NEW_FLAG: featureFlags.NEW_FLAG,
            surveyLogic: (await import('scenes/surveys/surveyLogic')).surveyLogic,
            SurveyFollowUpWorkflowButton: (await import('scenes/surveys/components/SurveyFollowUpWorkflowButton'))
                .SurveyFollowUpWorkflowButton,
            openIssueWorkflow: (
                await import('products/error_tracking/frontend/scenes/ErrorTrackingIssueScene/issueWorkflow')
            ).openIssueWorkflow,
            surveyRespondentsBroadcastLogic: (await import('scenes/surveys/components/surveyRespondentsBroadcastLogic'))
                .surveyRespondentsBroadcastLogic,
            enrolledPeopleAudience: (await import('products/early_access_features/frontend/enrolledPeopleAudience'))
                .enrolledPeopleAudience,
            BroadcastScene: (await import('../Broadcasts/BroadcastScene')).BroadcastScene,
            urlForNewBroadcastWithAudience: (await import('../Broadcasts/broadcastAudiencePrefill'))
                .urlForNewBroadcastWithAudience,
            WorkflowScene: (await import('../Workflows/WorkflowScene')).WorkflowScene,
            urlForNewWorkflowWithTrigger: (await import('../Workflows/workflowTriggerPrefill'))
                .urlForNewWorkflowWithTrigger,
            ATTEMPT_PREFILL_PARAM: (await import('./messageAudienceAttempts')).ATTEMPT_PREFILL_PARAM,
            MessageAudienceButton: (await import('./MessageAudienceButton')).MessageAudienceButton,
        }
    }, 60_000)

    beforeEach(() => {
        app.initKeaTests()
        sentEvents.length = 0
        createRequests.length = 0
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
                [AccessControlResourceType.Workflow]: AccessControlLevel.Editor,
            },
        }
    })

    afterEach(() => {
        app.toastify.toast.dismiss()
        app.rtl.cleanup()
    })

    const projectId = (): number => app.ApiConfig.getCurrentProjectId()

    const useSendMocks = ({ senders, sandbox }: { senders: object[]; sandbox?: object }): void => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': { email_sending_suspended: false },
                '/api/projects/:team_id/workflow_email_sandbox/status/': sandbox ?? {
                    ...testSender,
                    adoption_enabled: false,
                },
                '/api/projects/:team_id/integrations/': { count: senders.length, results: senders, next: null },
                '/api/projects/:team_id/cohorts/': { count: 0, results: [], next: null },
                '/api/projects/:team_id/cohorts/:id/': ({ params }) =>
                    String(params.id) === '42' ? { ...flagCohort, is_calculating: false } : readyList,
                [`/api/projects/:team_id/feature_flags/1/`]: { ...app.NEW_FLAG, id: 1, key: 'test-flag' },
                [`/api/projects/:team_id/surveys/${SURVEY_ID}/`]: survey,
                [`/api/projects/:team_id/surveys/${SURVEY_ID}/archived-response-uuids/`]: [],
                '/api/projects/:team_id/early_access_feature/:id': earlyAccessFeature,
                '/api/projects/:team_id/hog_flows/:id/': () => [200, { ...createRequests.at(-1), id: CREATED_ID }],
            },
            post: {
                [`${INGESTION_HOST}/e/`]: async ({ request }: MockResolverInfo) => {
                    sentEvents.push(...((await request.json()) as { batch: SentEvent[] }).batch)
                    return [200, { status: 1 }]
                },
                '/api/environments/:team_id/query/:kind/': { results: [[3, 2]] },
                '/api/environments/:team_id/query/': { results: [[3, 2]] },
                '/api/projects/:team_id/cohorts/': [201, readyList],
                '/api/projects/:team_id/feature_flags/1/create_static_cohort_for_flag/': [
                    201,
                    { cohort: { ...flagCohort, is_calculating: true } },
                ],
                '/api/projects/:team_id/workflow_email_drafts/': [500, { detail: 'down' }],
                '/api/projects/:team_id/hog_flows/': async ({ request }: MockResolverInfo) => {
                    const body = (await request.json()) as Record<string, unknown>
                    createRequests.push(body)
                    return [201, { ...body, id: CREATED_ID }]
                },
            },
            patch: {
                '/api/projects/:team_id/early_access_feature/:id': async ({ request }: MockResolverInfo) => [
                    200,
                    { ...earlyAccessFeature, ...((await request.json()) as object) },
                ],
            },
        })
    }

    const sentAttempts = async (count: number): Promise<unknown[]> =>
        await app.rtl.waitFor(() => {
            const attempts = sentEvents
                .filter(({ event }) => event === 'message audience clicked')
                .map(({ properties }) => properties.attempt_id)
            expect(attempts).toHaveLength(count)
            return attempts
        })

    const opened = async (path: string): Promise<void> =>
        await app.rtl.waitFor(() =>
            expect(app.router.values.location.pathname).toEqual(`/project/${projectId()}${path}`)
        )

    const createdOnClick = async (control: HTMLElement, broadcast: boolean): Promise<unknown> => {
        app.rtl.fireEvent.click(control)
        const created = await app.rtl.waitFor(() => {
            const own = createRequests.filter((body) => (body.origin_product === 'broadcasts') === broadcast)
            expect(own).toHaveLength(1)
            return own[0]
        })
        await app.rtl.waitFor(() => expect(app.router.values.location.pathname).toContain(CREATED_ID))
        return created.entry_attempt_id
    }

    const savedAttempt: Record<MessageAudienceDestination, () => Promise<unknown>> = {
        workflow: async () => {
            app.rtl.cleanup()
            const { container } = app.rtl.render(<app.WorkflowScene id="new" tab="workflow" />)
            const save = await app.rtl.waitFor(() => {
                const button = container.querySelector<HTMLElement>('[data-attr="workflow-save"]')
                expect(button).toBeEnabled()
                return button!
            })
            return await createdOnClick(save, false)
        },
        broadcast: async () => {
            app.rtl.cleanup()
            const { container } = app.rtl.render(<app.BroadcastScene id="new" />)
            const content = await app.rtl.waitFor(() => {
                const step = container.querySelector<HTMLElement>('[data-attr="broadcast-wizard-step-content"]')
                expect(step).toBeEnabled()
                return step!
            })
            return await createdOnClick(content, true)
        },
    }

    it.each<{ destination: MessageAudienceDestination; label: string; how: string; warning?: string }>([
        { destination: 'workflow', label: 'Build a custom workflow', how: 'directly' },
        { destination: 'broadcast', label: 'Send a one-time email', how: 'directly' },
        {
            destination: 'workflow',
            label: 'Build a custom workflow',
            how: 'through Continue',
            warning: TEST_SENDER_FOR_WORKFLOW,
        },
        { destination: 'broadcast', label: 'Send a one-time email', how: 'through Continue', warning: NO_SENDER },
    ])(
        'saves the attempt of the sent click event in the $destination opened $how',
        async ({ destination, label, warning }) => {
            useSendMocks(warning ? { senders: [], sandbox: testSender } : { senders: [verified] })
            app.router.actions.push('/project/997/early_access_features/1')
            const { fireEvent, render, screen, waitFor } = app.rtl
            render(
                <app.MessageAudienceButton
                    audience={app.enrolledPeopleAudience(earlyAccessFeature, 'early_access')}
                    label="Email opted-in users"
                />
            )

            fireEvent.click(screen.getByText('Email opted-in users'))
            fireEvent.click(await screen.findByText(label))
            if (warning) {
                expect(await screen.findByText(warning)).toBeInTheDocument()
                fireEvent.click(screen.getByText('Continue'))
                await waitFor(() => expect(screen.queryByText('Before you send')).not.toBeInTheDocument())
            }
            await opened(destination === 'workflow' ? app.urls.workflowNew() : app.urls.broadcastNew())

            const [attempt] = await sentAttempts(1)
            expect(attempt).toMatch(UUID)
            expect(await savedAttempt[destination]()).toEqual(attempt)
        }
    )

    it('saves the first sent attempt when a second cohort toast is clicked during its checks', async () => {
        useSendMocks({ senders: [verified] })
        app.router.actions.push('/project/997/cohorts/7')
        app.rtl.render(<app.toastify.ToastContainer />)
        app.cohortSavedToast({ id: 7, name: 'Signups' }, 'cohort_saved', 'first-save')
        app.cohortSavedToast({ id: 7, name: 'Signups' }, 'cohort_saved', 'second-save')
        const buttons = await app.rtl.waitFor(() => {
            const found = document.querySelectorAll<HTMLElement>(
                '[data-attr="message-audience-cohort_saved-broadcast"]'
            )
            expect(found).toHaveLength(2)
            return found
        })

        app.rtl.fireEvent.click(buttons[0])
        app.rtl.fireEvent.click(buttons[1])
        await opened(app.urls.broadcastNew())

        const [first, second] = await sentAttempts(2)
        expect(first).toMatch(UUID)
        expect(second).toMatch(UUID)
        expect(second).not.toEqual(first)
        expect(await savedAttempt.broadcast()).toEqual(first)
    })

    it.each([
        { how: 'from the toast after leaving the flag page', leave: true },
        { how: 'right away while still on the flag page', leave: false },
    ])('saves the sent attempt in the broadcast opened $how', async ({ leave }) => {
        useSendMocks({ senders: [verified] })
        app.router.actions.push(app.urls.featureFlag(1))
        app.rtl.render(<app.toastify.ToastContainer />)
        const logic = app.featureFlagLogic({ id: 1 })
        logic.mount()

        logic.actions.findOrCreateBroadcastCohort()
        if (leave) {
            app.router.actions.push(app.urls.cohorts())
            app.rtl.fireEvent.click(await app.rtl.screen.findByText('Open broadcast', undefined, { timeout: 5000 }))
        }
        await opened(app.urls.broadcastNew())
        logic.unmount()

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(await savedAttempt.broadcast()).toEqual(attempt)
    })

    it('saves the sent attempt in the broadcast opened from the toast of a flag that went live', async () => {
        useSendMocks({ senders: [verified] })
        let live = false
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/1/': () => [
                    200,
                    {
                        ...app.NEW_FLAG,
                        id: 1,
                        key: 'test-flag',
                        active: live,
                        filters: { groups: [{ properties: [], rollout_percentage: 100 }] },
                    },
                ],
            },
        })
        app.appFeatureFlagLogic.actions.setFeatureFlags([app.FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION], {
            [app.FEATURE_FLAGS.FEATURE_FLAG_COHORT_CREATION]: true,
        })
        app.router.actions.push(app.urls.featureFlag(1))
        app.rtl.render(<app.toastify.ToastContainer />)
        const logic = app.featureFlagLogic({ id: 1 })
        logic.mount()
        await app.rtl.waitFor(() => expect(logic.values.featureFlag.id).toEqual(1))

        live = true
        logic.actions.saveFeatureFlagSuccess({ ...logic.values.featureFlag, active: true })
        app.rtl.fireEvent.click(
            await app.rtl.waitFor(() => {
                const button = document.querySelector<HTMLElement>('[data-attr="feature-flag-live-broadcast"]')
                expect(button).toBeInTheDocument()
                return button!
            })
        )
        await opened(app.urls.broadcastNew())
        logic.unmount()

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(sentEvents.find(({ event }) => event === 'message audience clicked')?.properties.source).toEqual(
            'feature_flag_live'
        )
        expect(await savedAttempt.broadcast()).toEqual(attempt)
    })

    it('saves the sent attempt in the broadcast opened from a survey to its respondents', async () => {
        useSendMocks({ senders: [verified] })
        app.router.actions.push(app.urls.survey(SURVEY_ID))
        const survey = app.surveyLogic({ id: SURVEY_ID })
        survey.mount()
        await app.rtl.waitFor(() => expect(survey.values.survey.id).toEqual(SURVEY_ID))
        const logic = app.surveyRespondentsBroadcastLogic({ surveyId: SURVEY_ID })
        logic.mount()

        logic.actions.emailRespondents({})
        await opened(app.urls.broadcastNew())
        logic.unmount()
        survey.unmount()

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(await savedAttempt.broadcast()).toEqual(attempt)
    })

    it.each<{ entry: string; click: () => Promise<void> }>([
        {
            entry: "a survey's follow-up button",
            click: async () => {
                app.rtl.render(<app.SurveyFollowUpWorkflowButton surveyId={SURVEY_ID} />)
                app.rtl.fireEvent.click(app.rtl.screen.getByText('Email everyone who responds'))
            },
        },
        {
            entry: "an issue's workflow action",
            click: async () => app.openIssueWorkflow('issue-1'),
        },
    ])('saves the sent attempt in the workflow opened from $entry', async ({ click }) => {
        useSendMocks({ senders: [verified] })
        app.router.actions.push(app.urls.survey(SURVEY_ID))

        await click()
        await opened(app.urls.workflowNew())

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(await savedAttempt.workflow()).toEqual(attempt)
    })

    const openFileMenuItem = async (dataAttr: string): Promise<void> => {
        const { screen } = app.rtl
        const user = userEvent.setup({ pointerEventsCheck: PointerEventsCheckLevel.Never })
        await user.click(await screen.findByText('File', undefined, { timeout: 5000 }))
        app.rtl.fireEvent.click(await screen.findByText('Create'))
        app.rtl.fireEvent.click(
            await app.rtl.waitFor(() => {
                const item = document.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`)
                expect(item).toBeInTheDocument()
                return item!
            })
        )
    }

    it.each<{ entry: string; destination: MessageAudienceDestination; click: () => Promise<void> }>([
        {
            entry: "the cohort panel's workflow action",
            destination: 'workflow',
            click: async () => {
                await app.rtl.screen.findByText('Build a custom workflow', {}, { timeout: 5000 })
                app.rtl.fireEvent.click(
                    document.querySelector<HTMLElement>('[data-attr="cohort-message-with-workflow"]')!
                )
            },
        },
        {
            entry: "the cohort File menu's email item",
            destination: 'broadcast',
            click: async () => await openFileMenuItem('cohort-menubar-send-broadcast'),
        },
        {
            entry: "the cohort File menu's workflow item",
            destination: 'workflow',
            click: async () => await openFileMenuItem('cohort-menubar-message-with-workflow'),
        },
    ])('saves the sent attempt in the $destination opened from $entry', async ({ destination, click }) => {
        useSendMocks({ senders: [verified] })
        app.appFeatureFlagLogic.actions.setFeatureFlags([app.FEATURE_FLAGS.SCENE_MENU_BAR], {
            [app.FEATURE_FLAGS.SCENE_MENU_BAR]: true,
        })
        app.router.actions.push(app.urls.cohort(7))
        const panelHost = document.createElement('div')
        document.body.appendChild(panelHost)
        app.sceneLayoutLogic.mount()
        app.sceneLayoutLogic.actions.registerScenePanelElement(panelHost)
        app.rtl.render(<app.CohortEdit id={7} />)

        await click()
        await opened(destination === 'workflow' ? app.urls.workflowNew() : app.urls.broadcastNew())
        panelHost.remove()

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(await savedAttempt[destination]()).toEqual(attempt)
    })

    it('saves the sent attempt in the broadcast opened from the release toast of an early access feature', async () => {
        useSendMocks({ senders: [verified] })
        app.router.actions.push(app.urls.earlyAccessFeature(earlyAccessFeature.id))
        app.rtl.render(<app.toastify.ToastContainer />)
        const logic = app.earlyAccessFeatureLogic({ id: earlyAccessFeature.id })
        logic.mount()
        await app.rtl.waitFor(() => expect(logic.values.earlyAccessFeature.stage).toEqual(EarlyAccessFeatureStage.Beta))

        logic.actions.saveEarlyAccessFeature({
            ...logic.values.earlyAccessFeature,
            stage: EarlyAccessFeatureStage.GeneralAvailability,
        })
        app.rtl.fireEvent.click(
            await app.rtl.waitFor(() => {
                const button = document.querySelector<HTMLElement>('[data-attr="early-access-ga-broadcast"]')
                expect(button).toBeInTheDocument()
                return button!
            })
        )
        await opened(app.urls.broadcastNew())
        logic.unmount()

        const [attempt] = await sentAttempts(1)
        expect(attempt).toMatch(UUID)
        expect(await savedAttempt.broadcast()).toEqual(attempt)
    })

    it.each<MessageAudienceDestination>(['workflow', 'broadcast'])(
        'saves no attempt in a %s opened from a hand-edited attempt link',
        async (destination) => {
            useSendMocks({ senders: [verified] })
            const properties: MessageAudience['properties'] = [
                { key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In },
            ]
            const link =
                destination === 'workflow'
                    ? app.urlForNewWorkflowWithTrigger({ type: 'batch', filters: { properties } })
                    : app.urlForNewBroadcastWithAudience({ properties })
            app.router.actions.push(app.combineUrl(link, { [app.ATTEMPT_PREFILL_PARAM]: 'not-an-attempt' }).url)

            expect(await savedAttempt[destination]()).toBeUndefined()
        }
    )
})
