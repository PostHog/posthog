import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { getContext } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AccessControlResourceType,
    EarlyAccessFeatureStage,
    EarlyAccessFeatureType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { enrolledPeopleAudience } from 'products/early_access_features/frontend/enrolledPeopleAudience'

import { broadcastWizardLogic } from '../Broadcasts/broadcastWizardLogic'
import { workflowLogic } from '../Workflows/workflowLogic'
import { MessageAudience, MessageAudienceDestination } from './messageAudience'
import { MessageAudienceButton } from './MessageAudienceButton'
import { loadMessageAudienceWarnings } from './messageAudienceWarnings'

const SUSPENDED = 'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.'
const LIST_MATCHING = '"Signups" is still matching people. You can launch when it finishes.'
const NO_SENDER = 'Set up an email sender before sending'
const TEST_SENDER_FOR_WORKFLOW =
    "You don't have a verified email sender yet. You can send a test from the PostHog test sender to verified members of your organization. To email your users, set up your own domain."

const testSender = {
    integration_id: null,
    from_address: 'test@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const noTestSender = { ...testSender, adoption_enabled: false }

const verified = { id: 1, kind: 'email', config: { verified: true } }
const unverified = { id: 2, kind: 'email', config: { verified: false } }
const readyList = { id: 7, name: 'Signups', is_static: true, is_calculating: false, last_calculation: null }
const matchingList = { ...readyList, is_calculating: true }
const audience: MessageAudience = {
    source: 'cohort',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

type Answer = object | 'fails' | 'hangs'

const PAGE_SIZE = 100

interface Environment {
    suspended?: boolean | 'hangs'
    senders?: object[] | Answer
    morePages?: boolean
    sandbox?: Answer
    cohort?: Answer
    draftRequests?: unknown[]
}

const answer = (value: Answer): Promise<unknown> | [number, object] | object =>
    value === 'hangs' ? new Promise(() => {}) : value === 'fails' ? [500, { detail: 'down' }] : value

function useEnvironmentMocks(environments: Record<string, Environment>): void {
    const environment = (params: Record<string, unknown>): Environment | undefined =>
        environments[String(params.team_id)]
    useMocks({
        get: {
            '/api/projects/:team_id/hog_flows/email_sending_suspension/': ({ params }) => {
                const suspended = environment(params)?.suspended ?? false
                return suspended === 'hangs' ? new Promise(() => {}) : { email_sending_suspended: suspended }
            },
            '/api/projects/:team_id/workflow_email_sandbox/status/': ({ params }) => {
                const found = environment(params)
                return found ? answer(found.sandbox ?? noTestSender) : [404, { detail: 'Not found.' }]
            },
            '/api/projects/:team_id/integrations/': ({ params, request }) => {
                const found = environment(params)
                if (!found || new URL(request.url).searchParams.get('kind') !== 'email') {
                    return [404, { detail: 'Not found.' }]
                }
                const senders = found.senders ?? [verified]
                if (!Array.isArray(senders)) {
                    return answer(senders)
                }
                if (!found.morePages) {
                    return { count: senders.length, results: senders, next: null }
                }
                const page = Array.from({ length: PAGE_SIZE }, (_, index) => ({
                    ...senders[index % senders.length],
                    id: index + 1,
                }))
                const next = new URL(request.url)
                next.searchParams.set('limit', String(PAGE_SIZE))
                next.searchParams.set('offset', String(PAGE_SIZE))
                return { count: PAGE_SIZE + 1, results: page, next: next.toString() }
            },
            '/api/projects/:team_id/cohorts/:id/': ({ params }) => {
                const found = environment(params)
                return found && String(params.id) === '7'
                    ? answer(found.cohort ?? readyList)
                    : [404, { detail: 'Not found.' }]
            },
        },
        post: {
            '/api/projects/:team_id/workflow_email_drafts/': async ({ params, request }) => {
                environment(params)?.draftRequests?.push(await request.json())
                return [500, { detail: 'down' }]
            },
        },
    })
}

describe('message audience warnings', () => {
    const projectId = (): number => ApiConfig.getCurrentProjectId()
    const draftRequests: unknown[] = []

    beforeEach(() => {
        initKeaTests()
        draftRequests.length = 0
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it.each<{
        case: string
        destination: MessageAudienceDestination
        environment?: Environment
        caller?: 'dialog' | 'other'
        expected: string[]
    }>([
        { case: 'nothing wrong', destination: 'broadcast', expected: [] },
        {
            case: 'no sender while sending is suspended',
            destination: 'broadcast',
            environment: { suspended: true, senders: [] },
            expected: [SUSPENDED, NO_SENDER],
        },
        {
            case: 'only unverified senders',
            destination: 'broadcast',
            environment: { senders: [unverified] },
            expected: ["Verify the sender's domain before sending"],
        },
        {
            case: 'unverified senders on the first of several pages',
            destination: 'broadcast',
            environment: { senders: [unverified], morePages: true },
            expected: [],
        },
        {
            case: 'a list still matching',
            destination: 'broadcast',
            environment: { cohort: matchingList },
            expected: [LIST_MATCHING],
        },
        {
            case: 'a workflow, which ignores the list',
            destination: 'workflow',
            environment: { cohort: matchingList },
            expected: [],
        },
        {
            case: 'checks that fail',
            destination: 'broadcast',
            environment: { senders: 'fails', cohort: 'fails' },
            expected: [],
        },
        {
            case: 'a sender list without results',
            destination: 'broadcast',
            environment: { senders: { detail: 'unexpected' }, sandbox: testSender },
            expected: [],
        },
        {
            case: 'only the test sender, for a workflow',
            destination: 'workflow',
            environment: { senders: [], sandbox: testSender },
            expected: [TEST_SENDER_FOR_WORKFLOW],
        },
        {
            case: 'only unverified senders next to the test sender, for a workflow',
            destination: 'workflow',
            environment: { senders: [unverified], sandbox: testSender },
            expected: [TEST_SENDER_FOR_WORKFLOW],
        },
        {
            case: "today's warning for a broadcast, which cannot send from the test sender",
            destination: 'broadcast',
            environment: { senders: [], sandbox: testSender },
            expected: [NO_SENDER],
        },
        {
            case: 'the test sender while sending is suspended',
            destination: 'workflow',
            environment: { suspended: true, senders: [], sandbox: testSender },
            expected: [SUSPENDED, NO_SENDER],
        },
        {
            case: 'a verified sender next to the test sender',
            destination: 'workflow',
            environment: { senders: [verified], sandbox: testSender },
            expected: [],
        },
        {
            case: 'a test sender the project cannot adopt',
            destination: 'workflow',
            environment: { senders: [], sandbox: noTestSender },
            expected: [NO_SENDER],
        },
        {
            case: 'a blocked organization that already has a test sender',
            destination: 'workflow',
            environment: { senders: [], sandbox: { ...testSender, integration_id: 12, organization_blocked: true } },
            expected: [NO_SENDER],
        },
        {
            case: 'a test sender status that fails',
            destination: 'workflow',
            environment: { senders: [], sandbox: 'fails' },
            expected: [NO_SENDER],
        },
        {
            case: 'the test sender to a caller that does not offer it',
            destination: 'workflow',
            environment: { senders: [], sandbox: testSender },
            caller: 'other',
            expected: [NO_SENDER],
        },
    ])('reports $case', async ({ destination, environment = {}, caller = 'dialog', expected }) => {
        useEnvironmentMocks({ [projectId()]: environment })

        const warnings =
            caller === 'dialog'
                ? loadMessageAudienceWarnings(audience, destination, { offerTestSender: true })
                : loadMessageAudienceWarnings(audience, destination)
        expect(await warnings).toEqual(expected)
    })

    it.each<{ check: string; environment: Environment }>([
        { check: 'suspension', environment: { suspended: 'hangs', senders: [], sandbox: testSender } },
        { check: 'test sender status', environment: { senders: [], sandbox: 'hangs' } },
    ])('gives up on a $check check that never answers', async ({ environment }) => {
        jest.useFakeTimers()
        useEnvironmentMocks({ [projectId()]: environment })

        const warnings = loadMessageAudienceWarnings(audience, 'workflow', { offerTestSender: true })
        await jest.advanceTimersByTimeAsync(5000)

        expect(await warnings).toEqual([NO_SENDER])
    })

    it.each<MessageAudienceDestination>(['workflow', 'broadcast'])(
        'answers a %s without the test sender status when a verified sender leaves it nothing to change',
        async (destination) => {
            jest.useFakeTimers()
            useEnvironmentMocks({ [projectId()]: { senders: [verified], sandbox: 'hangs' } })

            let warnings: string[] | undefined
            void loadMessageAudienceWarnings(audience, destination, { offerTestSender: true }).then((result) => {
                warnings = result
            })
            await jest.advanceTimersByTimeAsync(1000)

            expect(warnings).toEqual([])
        }
    )

    it.each<{
        case: string
        destination: MessageAudienceDestination
        project: Environment
        selected: Environment
        expected: string[]
    }>(
        (['workflow', 'broadcast'] as const).flatMap((destination) => [
            {
                case: `a ${destination} warns about its project`,
                destination,
                project: { suspended: true, senders: [verified], sandbox: noTestSender, cohort: matchingList },
                selected: { suspended: false, senders: [], sandbox: testSender, cohort: readyList },
                expected: [SUSPENDED],
            },
            {
                case: `a ${destination} warns about no suspension the project does not have`,
                destination,
                project: { suspended: false, senders: [], sandbox: testSender, cohort: matchingList },
                selected: { suspended: true, senders: [], sandbox: testSender, cohort: readyList },
                expected: [NO_SENDER],
            },
            {
                case: `a ${destination} offers no test sender outside the project's own environment`,
                destination,
                project: { suspended: false, senders: [], sandbox: testSender, cohort: matchingList },
                selected: { suspended: false, senders: [], sandbox: testSender, cohort: readyList },
                expected: [NO_SENDER],
            },
        ])
    )('reads the checks where they apply: $case', async ({ destination, project, selected, expected }) => {
        const teamId = ApiConfig.getCurrentTeamId()
        useEnvironmentMocks({ [projectId()]: project, [projectId() + 1]: selected })
        try {
            ApiConfig.setCurrentTeamId(projectId() + 1)

            expect(await loadMessageAudienceWarnings(audience, destination, { offerTestSender: true })).toEqual(
                destination === 'broadcast' ? [...expected, LIST_MATCHING] : expected
            )
        } finally {
            ApiConfig.setCurrentTeamId(teamId)
        }
    })

    const earlyAccessFeature = {
        id: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
        name: 'Dark mode',
        description: 'A darker theme',
        stage: EarlyAccessFeatureStage.Beta,
        feature_flag: { id: 1, key: 'dark-mode' },
    } as EarlyAccessFeatureType
    const earlyAccess = enrolledPeopleAudience(earlyAccessFeature, 'early_access')

    const openedEditor: Record<MessageAudienceDestination, () => Promise<unknown>> = {
        workflow: async () => {
            const { WorkflowScene } = await import('../Workflows/WorkflowScene')
            render(<WorkflowScene id="new" tab="workflow" />)
            await waitFor(() => expect(draftRequests).toHaveLength(1))
            const logic = Object.values(getContext().mount.mounted).find((mounted) =>
                mounted.pathString.startsWith('products.workflows.frontend.Workflows.workflowLogic.workflow-new-')
            ) as ReturnType<typeof workflowLogic> | undefined
            const { actions } = logic!.values.workflow
            const trigger = actions.find((action) => action.type === 'trigger')?.config
            const email = actions.find((action) => action.type === 'email_sandbox' || action.type === 'function_email')
            return {
                trigger: trigger?.type,
                step: email?.type,
                subject: (email?.config as Record<string, any> | undefined)?.inputs?.email?.value?.subject,
                draftRequest: draftRequests[0],
            }
        },
        broadcast: async () => {
            const logic = broadcastWizardLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            return { audience: logic.values.audienceProperties, name: logic.values.name }
        },
    }

    it.each<{ destination: MessageAudienceDestination; label: string; warning: string; path: string; opens: unknown }>([
        {
            destination: 'workflow',
            label: 'Build a custom workflow',
            warning: TEST_SENDER_FOR_WORKFLOW,
            path: urls.workflowNew(),
            opens: {
                trigger: 'event',
                step: 'email_sandbox',
                subject: earlyAccess.workflowEmail?.subject,
                draftRequest: earlyAccess.draftSource,
            },
        },
        {
            destination: 'broadcast',
            label: 'Send a one-time email',
            warning: NO_SENDER,
            path: urls.broadcastNew(),
            opens: { audience: earlyAccess.properties, name: earlyAccess.broadcastName },
        },
    ])(
        'asks before a $destination with no sender, and Continue opens it',
        async ({ label, warning, path, destination, opens }) => {
            useEnvironmentMocks({
                [projectId()]: { senders: [], sandbox: { ...testSender, integration_id: 12 }, draftRequests },
            })
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT!,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
                    [AccessControlResourceType.Workflow]: AccessControlLevel.Editor,
                },
            }
            router.actions.push('/project/997/early_access_features/1')
            render(<MessageAudienceButton audience={earlyAccess} label="Email opted-in users" />)

            fireEvent.click(screen.getByText('Email opted-in users'))
            fireEvent.click(await screen.findByText(label))

            expect(await screen.findByText(warning)).toBeInTheDocument()
            expect(screen.getByText('Set up email')).toBeInTheDocument()
            expect(router.values.location.pathname).toEqual('/project/997/early_access_features/1')

            fireEvent.click(screen.getByText('Continue'))
            await waitFor(() => expect(router.values.location.pathname).toEqual(`/project/${projectId()}${path}`))
            await waitFor(() => expect(screen.queryByText(warning)).not.toBeInTheDocument())
            expect(await openedEditor[destination]()).toEqual(opens)
        }
    )
})
