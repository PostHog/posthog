import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowRates as workflow } from './reputationFixtures'
import { workflowsReputationLogic } from './workflowsReputationLogic'

// The newsletter causes the most bounces in absolute terms but only because it sends the most:
// its rate matches the project's. The import bounces far more than its volume predicts.
const NEWSLETTER = workflow('wf-newsletter', 'Newsletter', {
    emails_sent: 8000,
    bounce_rate: 0.02,
    complaint_rate: 0.0002,
})
const OLD_IMPORT = workflow('wf-import', 'Old list import', {
    emails_sent: 1500,
    bounce_rate: 0.06,
    complaint_rate: 0.0003,
})
const ONBOARDING = workflow('wf-onboarding', 'Onboarding', {
    emails_sent: 1000,
    bounce_rate: 0.035,
    complaint_rate: 0.0002,
})
const WIN_BACK = workflow(
    'wf-win-back',
    'Win-back',
    { emails_sent: 400, bounce_rate: 0.08, complaint_rate: 0.004 },
    'Paused because the hard bounce rate reached 8%.'
)

const HEALTHY: TeamEmailReputationResponseApi = {
    aws: { health: 'healthy', sending_status: 'ENABLED', findings: [] },
    reputation: { bounce_rate: 0.004, complaint_rate: 0.0001, emails_sent: 20000 },
    workflows: [workflow('wf-digest', 'Digest', { emails_sent: 20000, bounce_rate: 0.004, complaint_rate: 0.0001 })],
    isps: [
        {
            isp: 'Gmail',
            emails_sent: 15000,
            delivery_rate: 0.99,
            bounce_rate: 0.003,
            transient_bounce_rate: 0.01,
            complaint_rate: null,
            complaint_base: 0,
            unavailable: [],
        },
    ],
    isp_shared_domains: [],
    isp_withheld_domains: [],
    email_sending_suspended: false,
    email_sending_suspended_at: null,
    email_sending_suspension_reason: '',
    sending_allowance: null,
}

const NEEDS_WORK: TeamEmailReputationResponseApi = {
    ...HEALTHY,
    aws: {
        health: 'critical',
        sending_status: 'ENABLED',
        findings: [
            { finding_type: 'DMARC', impact: 'LOW', description: 'DMARC1', last_updated_at: null },
            { finding_type: 'BOUNCE', impact: 'HIGH', description: 'Bounce rate', last_updated_at: null },
        ],
    },
    reputation: { bounce_rate: 0.029, complaint_rate: 0.0003, emails_sent: 10900 },
    workflows: [WIN_BACK, OLD_IMPORT, ONBOARDING, NEWSLETTER],
    isps: [
        ...HEALTHY.isps,
        {
            isp: 'Yahoo',
            emails_sent: 2000,
            delivery_rate: 0.93,
            bounce_rate: 0.045,
            transient_bounce_rate: 0.02,
            complaint_rate: 0.0005,
            complaint_base: 1800,
            unavailable: [],
        },
        {
            // Too little volume to judge: one bounce here reads as 50%.
            isp: 'Aol',
            emails_sent: 2,
            delivery_rate: 0.5,
            bounce_rate: 0.5,
            transient_bounce_rate: 0,
            complaint_rate: 0,
            complaint_base: 1,
            unavailable: [],
        },
        {
            isp: 'Hotmail',
            emails_sent: 3000,
            delivery_rate: null,
            bounce_rate: null,
            transient_bounce_rate: null,
            complaint_rate: null,
            complaint_base: 0,
            unavailable: ['delivery', 'bounce', 'transient_bounce', 'complaint'],
        },
    ],
}

describe('workflowsReputationLogic', () => {
    let logic: ReturnType<typeof workflowsReputationLogic.build>

    function reputationMocks(response: TeamEmailReputationResponseApi): Parameters<typeof useMocks>[0] {
        return {
            get: {
                '/api/projects/:team_id/hog_flows/reputation/': (req) => {
                    const search = new URL(req.request.url).searchParams.get('search')?.toLowerCase()
                    return [
                        200,
                        search
                            ? {
                                  ...response,
                                  workflows: response.workflows.filter((w) =>
                                      w.hog_flow_name.toLowerCase().includes(search)
                                  ),
                              }
                            : response,
                    ]
                },
            },
        }
    }

    function mountLogic(path?: string): void {
        initKeaTests()
        if (path) {
            router.actions.push(path)
        }
        logic = workflowsReputationLogic()
        logic.mount()
    }

    async function search(term: string): Promise<void> {
        logic.actions.setSearch(term)
        await jest.advanceTimersByTimeAsync(250)
    }

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('lists what to fix worst first, pointing each item where it gets fixed', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])

        expect(logic.values.reputationActions).toEqual([
            partial({
                key: 'paused:wf-win-back',
                severity: 'high',
                primary: partial({ to: urls.workflow('wf-win-back', 'workflow') }),
            }),
            partial({
                key: 'finding:BOUNCE',
                severity: 'high',
                primary: partial({ to: urls.workflow('wf-import', 'workflow') }),
            }),
            partial({
                key: 'finding:DMARC',
                severity: 'medium',
                primary: partial({ to: urls.workflows('channels') }),
            }),
            partial({
                key: 'workflow-bounce:wf-onboarding',
                severity: 'low',
                primary: partial({ to: urls.workflow('wf-onboarding', 'workflow') }),
            }),
            partial({
                key: 'provider-bounce:Yahoo',
                severity: 'low',
            }),
        ])
    })

    it.each([
        [urls.workflows('reputation'), urls.workflows('channels')],
        [urls.broadcasts('reputation'), urls.broadcasts('channels')],
    ])('keeps the fix links on the surface of %s', async (path, channelsUrl) => {
        useMocks(reputationMocks(NEEDS_WORK))
        mountLogic(path)

        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])

        expect(logic.values.reputationActions.find((item) => item.key === 'finding:DMARC')?.primary.to).toEqual(
            channelsUrl
        )
    })

    it.each([
        ['every signal is healthy', HEALTHY, true],
        [
            'there is no email at all',
            { ...HEALTHY, reputation: null, workflows: [], isps: [] } as TeamEmailReputationResponseApi,
            false,
        ],
    ])('has nothing to fix when %s', async (_, response, hasSendingData) => {
        useMocks(reputationMocks(response))
        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])

        expect(logic.values.reputationActions).toEqual([])
        expect(logic.values.hasSendingData).toBe(hasSendingData)
    })

    it.each([
        [403, 'forbidden'],
        [500, 'failed'],
    ])('tells a %s apart when the page fails to load', async (status, loadError) => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation/': [status, { detail: 'Nope' }] } })
        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadReputationFailure'])

        expect(logic.values.reputationLoadError).toEqual(loadError)
    })

    it('keeps the action list when a search narrows the workflow table', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])
        const actionKeys = logic.values.reputationActions.map((item) => item.key)
        jest.useFakeTimers()

        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        expect(logic.values.tableWorkflows.map((w) => w.hog_flow_id)).toEqual(['wf-onboarding'])
        expect(logic.values.reputationActions.map((item) => item.key)).toEqual(actionKeys)
    })

    it('shows the table as loading until the typed search has answered', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])
        jest.useFakeTimers()
        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        logic.actions.setSearch('win')

        expect(logic.values.tableLoading).toBe(true)
        expect(logic.values.tableWorkflows).toEqual([])
        await jest.advanceTimersByTimeAsync(250)
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])
        expect(logic.values.tableLoading).toBe(false)
        expect(logic.values.tableWorkflows.map((w) => w.hog_flow_id)).toEqual(['wf-win-back'])
    })

    it('says so when a search fails instead of keeping stale rows', async () => {
        useMocks(reputationMocks(NEEDS_WORK))
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadReputationSuccess'])
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation/': [500, { detail: 'Nope' }] } })
        jest.useFakeTimers()

        await search('onboarding')
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])

        expect(logic.values.tableWorkflows).toEqual([])
        expect(logic.values.workflowSearchFailed).toBe(true)
        expect(logic.values.tableLoading).toBe(false)
    })
})
