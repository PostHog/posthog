import '@testing-library/jest-dom'

import { fireEvent, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import {
    hogFlowsEmailSendingSuspensionRetrieve,
    workflowEmailSandboxStatus,
} from 'products/workflows/frontend/generated/api'

import { parseWorkflowTriggerPrefill } from '../Workflows/workflowTriggerPrefill'
import { DRAFT_SOURCE_PARAM, parseEmailDraftSource } from './aiEmailDraft'
import { MessageAudience, MessageAudienceDestination, captureMessageAudienceClicked } from './messageAudience'
import { ATTEMPT_PREFILL_PARAM, parseAttemptPrefill } from './messageAudienceAttempts'
import { MessageAudienceWarning, loadMessageAudienceWarnings, openMessageAudience } from './messageAudienceWarnings'
import { MessageDraft, parseMessageDraftPrefill } from './messageDrafts'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsRetrieve: jest.fn() }))
jest.mock('products/integrations/frontend/generated/api', () => ({ integrationsList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsEmailSendingSuspensionRetrieve: jest.fn(),
    workflowEmailSandboxStatus: jest.fn(),
}))

const SUSPENDED: MessageAudienceWarning = {
    kind: 'sending_suspended',
    message: 'Email sending is suspended for this project. Workflow and broadcast emails are not being delivered.',
}
const NO_SENDER: MessageAudienceWarning = { kind: 'no_sender', message: 'Set up an email sender before sending' }
const UNVERIFIED: MessageAudienceWarning = {
    kind: 'unverified_sender',
    message: "Verify the sender's domain before sending",
}
const LIST_MATCHING: MessageAudienceWarning = {
    kind: 'cohort_not_ready',
    message: '"Signups" is still matching people. You can launch when it finishes.',
}

const TEST_SENDER_FOR_WORKFLOW: MessageAudienceWarning = {
    kind: 'test_sender_only',
    message:
        "You don't have a verified email sender yet. You can send a test from the PostHog test sender to verified members of your organization. To email your users, set up your own domain.",
}
const TEST_SENDER_FOR_BROADCAST: MessageAudienceWarning = {
    kind: 'test_sender_only',
    message:
        "Broadcasts need a verified email sender, and you don't have one yet. To try this email first, continue in a workflow and send a test from the PostHog test sender to verified members of your organization.",
}

const testSender = {
    integration_id: null,
    from_address: 'test@example.com',
    display_name: 'Example via PostHog',
    organization_blocked: false,
    adoption_enabled: true,
}
const noTestSender = { ...testSender, adoption_enabled: false }

interface EnvironmentFixture {
    suspended: boolean
    senders: object[]
    sandbox: object
}

const verified = { kind: 'email', config: { verified: true } }
const unverified = { kind: 'email', config: { verified: false } }
const matchingList = { name: 'Signups', is_static: true, is_calculating: true, last_calculation: null }
const audience: MessageAudience = {
    source: 'cohort',
    properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
}

describe('loadMessageAudienceWarnings', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each<{
        case: string
        destination: MessageAudienceDestination
        suspended?: boolean
        senders?: object[] | Error
        morePages?: boolean
        cohort?: object | Error
        sandbox?: object | Error
        caller?: 'dialog' | 'other'
        expected: MessageAudienceWarning[]
    }>([
        { case: 'nothing wrong', destination: 'broadcast', expected: [] },
        {
            case: 'no sender while sending is suspended',
            destination: 'broadcast',
            suspended: true,
            senders: [],
            expected: [SUSPENDED, NO_SENDER],
        },
        {
            case: 'only unverified senders',
            destination: 'broadcast',
            senders: [unverified],
            expected: [UNVERIFIED],
        },
        {
            case: 'unverified senders on the first of several pages',
            destination: 'broadcast',
            senders: [unverified],
            morePages: true,
            expected: [],
        },
        { case: 'a list still matching', destination: 'broadcast', cohort: matchingList, expected: [LIST_MATCHING] },
        { case: 'a workflow, which ignores the list', destination: 'workflow', cohort: matchingList, expected: [] },
        {
            case: 'checks that fail',
            destination: 'broadcast',
            senders: new Error('down'),
            cohort: new Error('down'),
            expected: [],
        },
        {
            case: 'only the test sender, for a workflow',
            destination: 'workflow',
            senders: [],
            sandbox: testSender,
            expected: [TEST_SENDER_FOR_WORKFLOW],
        },
        {
            case: 'only the test sender, for a broadcast',
            destination: 'broadcast',
            senders: [unverified],
            sandbox: testSender,
            expected: [TEST_SENDER_FOR_BROADCAST],
        },
        {
            case: 'the test sender while sending is suspended',
            destination: 'broadcast',
            suspended: true,
            senders: [],
            sandbox: testSender,
            expected: [SUSPENDED, NO_SENDER],
        },
        {
            case: 'a verified sender next to the test sender',
            destination: 'workflow',
            senders: [verified],
            sandbox: testSender,
            expected: [],
        },
        {
            case: 'a test sender the project cannot adopt',
            destination: 'workflow',
            senders: [],
            sandbox: noTestSender,
            expected: [NO_SENDER],
        },
        {
            case: 'a blocked organization that already has a test sender',
            destination: 'workflow',
            senders: [],
            sandbox: { ...testSender, integration_id: 12, organization_blocked: true },
            expected: [NO_SENDER],
        },
        {
            case: 'a test sender status that fails',
            destination: 'workflow',
            senders: [],
            sandbox: new Error('down'),
            expected: [NO_SENDER],
        },
        {
            case: 'the test sender to a caller that does not offer it',
            destination: 'broadcast',
            senders: [],
            sandbox: testSender,
            caller: 'other',
            expected: [NO_SENDER],
        },
    ])(
        'reports $case',
        async ({
            destination,
            suspended = false,
            senders = [verified],
            morePages,
            cohort,
            sandbox,
            caller = 'dialog',
            expected,
        }) => {
            jest.mocked(workflowEmailSandboxStatus).mockImplementation(async () => {
                if (sandbox instanceof Error) {
                    throw sandbox
                }
                return (sandbox ?? noTestSender) as never
            })
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                email_sending_suspended: suspended,
            } as never)
            jest.mocked(integrationsList).mockImplementation(async () => {
                if (senders instanceof Error) {
                    throw senders
                }
                return { count: senders.length, results: senders, next: morePages ? 'page-2' : null } as never
            })
            jest.mocked(cohortsRetrieve).mockImplementation(async () => {
                if (cohort instanceof Error) {
                    throw cohort
                }
                return (cohort ?? { name: 'Signups', is_static: true, is_calculating: false }) as never
            })

            const warnings =
                caller === 'dialog'
                    ? loadMessageAudienceWarnings(audience, destination, { offerTestSender: true })
                    : loadMessageAudienceWarnings(audience, destination)
            expect(await warnings).toEqual(expected)
        }
    )

    it.each(['suspension', 'test sender status'])('gives up on a %s check that never answers', async (hanging) => {
        jest.useFakeTimers()
        try {
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockReturnValue(
                hanging === 'suspension'
                    ? new Promise(() => {})
                    : (Promise.resolve({ email_sending_suspended: false }) as never)
            )
            jest.mocked(workflowEmailSandboxStatus).mockReturnValue(
                hanging === 'test sender status' ? new Promise(() => {}) : (Promise.resolve(testSender) as never)
            )
            jest.mocked(integrationsList).mockResolvedValue({ count: 0, results: [], next: null } as never)

            const warnings = loadMessageAudienceWarnings(audience, 'workflow', { offerTestSender: true })
            await jest.advanceTimersByTimeAsync(5000)

            expect(await warnings).toEqual([NO_SENDER])
        } finally {
            jest.useRealTimers()
        }
    })

    it.each<{
        case: string
        destination: MessageAudienceDestination
        selected: 'same' | 'child'
        senders: object[]
        sandbox?: object
        expected: MessageAudienceWarning[]
    }>([
        {
            case: 'a verified sender leaves nothing for the test sender to change',
            destination: 'workflow',
            selected: 'same',
            senders: [verified],
            expected: [],
        },
        {
            case: 'a verified sender leaves nothing for the test sender to change',
            destination: 'broadcast',
            selected: 'child',
            senders: [verified],
            expected: [],
        },
        {
            case: 'the test sender is unavailable',
            destination: 'workflow',
            selected: 'child',
            senders: [],
            sandbox: noTestSender,
            expected: [NO_SENDER],
        },
    ])('answers a $destination at once when $case', async ({ destination, selected, senders, sandbox, expected }) => {
        jest.useFakeTimers()
        const projectId = String(ApiConfig.getCurrentProjectId())
        const teamId = ApiConfig.getCurrentTeamId()
        try {
            if (selected === 'child') {
                ApiConfig.setCurrentTeamId(teamId + 1)
            }
            const answersNow = (id: string): boolean => selected === 'same' || id === projectId
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockImplementation((id) =>
                answersNow(id) ? (Promise.resolve({ email_sending_suspended: false }) as never) : new Promise(() => {})
            )
            jest.mocked(integrationsList).mockImplementation((id) =>
                answersNow(id)
                    ? (Promise.resolve({ count: senders.length, results: senders, next: null }) as never)
                    : new Promise(() => {})
            )
            jest.mocked(workflowEmailSandboxStatus).mockReturnValue(
                sandbox ? (Promise.resolve(sandbox) as never) : new Promise(() => {})
            )
            jest.mocked(cohortsRetrieve).mockResolvedValue({
                name: 'Signups',
                is_static: true,
                is_calculating: false,
            } as never)

            let warnings: MessageAudienceWarning[] | undefined
            void loadMessageAudienceWarnings(audience, destination, { offerTestSender: true }).then((result) => {
                warnings = result
            })
            await jest.advanceTimersByTimeAsync(0)

            expect(warnings).toEqual(expected)
        } finally {
            ApiConfig.setCurrentTeamId(teamId)
            jest.useRealTimers()
        }
    })

    it.each<{
        case: string
        destination: MessageAudienceDestination
        project: EnvironmentFixture
        selected: EnvironmentFixture
        expected: MessageAudienceWarning[]
    }>(
        (['workflow', 'broadcast'] as const).flatMap((destination) => [
            {
                case: `a ${destination} warns about its project`,
                destination,
                project: { suspended: true, senders: [verified], sandbox: noTestSender },
                selected: { suspended: false, senders: [], sandbox: testSender },
                expected: [SUSPENDED],
            },
            {
                case: `a ${destination} warns about no suspension the project does not have`,
                destination,
                project: { suspended: false, senders: [], sandbox: testSender },
                selected: { suspended: true, senders: [], sandbox: testSender },
                expected: [NO_SENDER],
            },
            {
                case: `a ${destination} offers no test sender where the selected environment has its own sender`,
                destination,
                project: { suspended: false, senders: [], sandbox: testSender },
                selected: { suspended: false, senders: [verified], sandbox: testSender },
                expected: [NO_SENDER],
            },
            {
                case: `a ${destination} offers the test sender of the selected environment`,
                destination,
                project: { suspended: false, senders: [], sandbox: noTestSender },
                selected: { suspended: false, senders: [], sandbox: testSender },
                expected: [destination === 'workflow' ? TEST_SENDER_FOR_WORKFLOW : TEST_SENDER_FOR_BROADCAST],
            },
        ])
    )('reads the checks where they apply: $case', async ({ destination, project, selected, expected }) => {
        const projectId = ApiConfig.getCurrentProjectId()
        const teamId = ApiConfig.getCurrentTeamId()
        const environments: Record<string, EnvironmentFixture> = {
            [String(projectId)]: project,
            [String(projectId + 1)]: selected,
        }
        const environment = (id: string): EnvironmentFixture => {
            if (!environments[id]) {
                throw new Error(`no environment ${id}`)
            }
            return environments[id]
        }
        try {
            ApiConfig.setCurrentTeamId(projectId + 1)
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockImplementation(
                async (id) => ({ email_sending_suspended: environment(id).suspended }) as never
            )
            jest.mocked(workflowEmailSandboxStatus).mockImplementation(async (id) => environment(id).sandbox as never)
            jest.mocked(integrationsList).mockImplementation(async (id) => {
                const { senders } = environment(id)
                return { count: senders.length, results: senders, next: null } as never
            })
            jest.mocked(cohortsRetrieve).mockImplementation(async (id) => {
                if (id !== String(projectId)) {
                    throw new Error(`cohorts live in the project, not ${id}`)
                }
                return matchingList as never
            })

            expect(await loadMessageAudienceWarnings(audience, destination, { offerTestSender: true })).toEqual(
                destination === 'broadcast' ? [...expected, LIST_MATCHING] : expected
            )
        } finally {
            ApiConfig.setCurrentTeamId(teamId)
        }
    })

    it.each([
        {
            case: 'a sender problem',
            suspended: false,
            kinds: ['no_sender'],
            secondary: 'Set up email',
            landsOn: urls.workflows('channels'),
        },
        {
            case: 'only a suspension',
            suspended: true,
            senders: [verified],
            kinds: ['sending_suspended'],
            secondary: 'Cancel',
            landsOn: '/start',
        },
        {
            case: 'only the test sender',
            suspended: false,
            sandbox: testSender,
            kinds: ['test_sender_only'],
            secondary: 'Set up email',
            landsOn: urls.workflows('channels'),
        },
    ])(
        'reports the warnings it shows for $case, and $secondary takes the person to $landsOn',
        async ({ suspended, senders = [], sandbox = noTestSender, kinds, secondary, landsOn }) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            try {
                router.actions.push('/start')
                jest.mocked(workflowEmailSandboxStatus).mockResolvedValue(sandbox as never)
                jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                    email_sending_suspended: suspended,
                } as never)
                jest.mocked(integrationsList).mockResolvedValue({
                    count: senders.length,
                    results: senders,
                    next: null,
                } as never)

                captureMessageAudienceClicked('early_access', 'workflow')
                await openMessageAudience({ ...audience, source: 'early_access' }, 'workflow')

                const events = capture.mock.calls.map(([event, properties]) => ({ event, properties }))
                const [clicked, shown] = events
                expect(shown).toEqual({
                    event: 'message audience warnings shown',
                    properties: {
                        source: 'early_access',
                        destination: 'workflow',
                        attempt_id: clicked.properties?.attempt_id,
                        warnings: kinds,
                    },
                })
                fireEvent.click(await screen.findByText(secondary))
                await waitFor(() => expect(screen.queryByText('Before you send')).not.toBeInTheDocument())
                expect(router.values.location.pathname.endsWith(landsOn)).toBe(true)
            } finally {
                capture.mockRestore()
            }
        }
    )
    it.each<{
        case: string
        extra: Partial<MessageAudience>
        email: MessageDraft | null
        draftSource: MessageAudience['draftSource'] | null
    }>([
        {
            case: 'its email',
            extra: {
                broadcastEmail: { subject: 'Your survey answers', paragraphs: ['Hi there,', 'Thanks for answering.'] },
            },
            email: { subject: 'Your survey answers', paragraphs: ['Hi there,', 'Thanks for answering.'] },
            draftSource: null,
        },
        {
            case: 'the draft source of a cohort',
            extra: { draftSource: { source: 'cohort', source_id: '7' } },
            email: null,
            draftSource: { source: 'cohort', source_id: '7' },
        },
    ])(
        'continues a broadcast that only the test sender could send in a workflow with the same people, attempt and $case',
        async ({ extra, email, draftSource }) => {
            router.actions.push('/start')
            jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                email_sending_suspended: false,
            } as never)
            jest.mocked(integrationsList).mockResolvedValue({ count: 0, results: [], next: null } as never)
            jest.mocked(workflowEmailSandboxStatus).mockResolvedValue(testSender as never)
            jest.mocked(cohortsRetrieve).mockResolvedValue({
                name: 'Signups',
                is_static: true,
                is_calculating: false,
            } as never)
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            try {
                const source = `test_sender_handoff_${draftSource ? 'draft' : 'email'}`
                captureMessageAudienceClicked(source, 'broadcast')
                await openMessageAudience({ ...audience, source, ...extra }, 'broadcast')

                expect(await screen.findByText('Set up email')).toBeInTheDocument()
                fireEvent.click(await screen.findByText('Continue in a workflow'))
                await waitFor(() => expect(screen.queryByText('Before you send')).not.toBeInTheDocument())

                const [clicked] = capture.mock.calls.map(([, properties]) => properties)
                const { pathname, searchParams } = router.values.currentLocation
                expect(pathname.endsWith(urls.workflowNew())).toBe(true)
                expect(parseWorkflowTriggerPrefill(searchParams.trigger)).toEqual({
                    type: 'batch',
                    filters: { properties: audience.properties },
                })
                expect(parseMessageDraftPrefill(searchParams.email)).toEqual(email)
                expect(parseEmailDraftSource(searchParams[DRAFT_SOURCE_PARAM])).toEqual(draftSource)
                expect(parseAttemptPrefill(searchParams[ATTEMPT_PREFILL_PARAM])).toEqual(clicked?.attempt_id)
            } finally {
                capture.mockRestore()
            }
        }
    )
})
