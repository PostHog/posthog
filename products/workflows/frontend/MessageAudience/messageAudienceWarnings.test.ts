import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { cohortsRetrieve } from 'products/cohorts/frontend/generated/api'
import { integrationsList } from 'products/integrations/frontend/generated/api'
import {
    hogFlowsEmailSendingSuspensionRetrieve,
    workflowEmailSandboxStatus,
} from 'products/workflows/frontend/generated/api'

import { MessageAudience, MessageAudienceDestination } from './messageAudience'
import { loadMessageAudienceWarnings } from './messageAudienceWarnings'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsRetrieve: jest.fn() }))
jest.mock('products/integrations/frontend/generated/api', () => ({ integrationsList: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsEmailSendingSuspensionRetrieve: jest.fn(),
    workflowEmailSandboxStatus: jest.fn(),
}))

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
        senders?: object[] | object | Error
        morePages?: boolean
        cohort?: object | Error
        sandbox?: object | Error
        caller?: 'dialog' | 'other'
        expected: string[]
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
            expected: ["Verify the sender's domain before sending"],
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
            case: 'a sender list without results',
            destination: 'broadcast',
            senders: { detail: 'unexpected' },
            sandbox: testSender,
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
            case: "today's warning for a broadcast, which cannot send from the test sender",
            destination: 'broadcast',
            senders: [],
            sandbox: testSender,
            expected: [NO_SENDER],
        },
        {
            case: 'the test sender while sending is suspended',
            destination: 'workflow',
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
            destination: 'workflow',
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
                if (!Array.isArray(senders)) {
                    return senders as never
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

    it.each<MessageAudienceDestination>(['workflow', 'broadcast'])(
        'answers a %s at once when a verified sender leaves nothing for the test sender to change',
        async (destination) => {
            jest.useFakeTimers()
            try {
                jest.mocked(hogFlowsEmailSendingSuspensionRetrieve).mockResolvedValue({
                    email_sending_suspended: false,
                } as never)
                jest.mocked(integrationsList).mockResolvedValue({
                    count: 1,
                    results: [verified],
                    next: null,
                } as never)
                jest.mocked(workflowEmailSandboxStatus).mockReturnValue(new Promise(() => {}))
                jest.mocked(cohortsRetrieve).mockResolvedValue({
                    name: 'Signups',
                    is_static: true,
                    is_calculating: false,
                } as never)

                let warnings: string[] | undefined
                void loadMessageAudienceWarnings(audience, destination, { offerTestSender: true }).then((result) => {
                    warnings = result
                })
                await jest.advanceTimersByTimeAsync(0)

                expect(warnings).toEqual([])
            } finally {
                jest.useRealTimers()
            }
        }
    )

    it.each<{
        case: string
        destination: MessageAudienceDestination
        project: EnvironmentFixture
        selected: EnvironmentFixture
        expected: string[]
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
                case: `a ${destination} offers no test sender outside the project's own environment`,
                destination,
                project: { suspended: false, senders: [], sandbox: testSender },
                selected: { suspended: false, senders: [], sandbox: testSender },
                expected: [NO_SENDER],
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
})
