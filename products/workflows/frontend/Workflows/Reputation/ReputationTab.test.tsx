import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    IspSendingHealthApi,
    TeamEmailReputationResponseApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { workflowRates } from './reputationFixtures'
import { ReputationTab } from './ReputationTab'

const RESPONSE: TeamEmailReputationResponseApi = {
    aws: {
        health: 'warning',
        sending_status: 'ENABLED',
        findings: [{ finding_type: 'DMARC', impact: 'LOW', description: '', last_updated_at: null }],
    },
    reputation: { bounce_rate: 0.004, complaint_rate: 0.0001, emails_sent: 20000 },
    workflows: [workflowRates('wf-1', 'Digest', { emails_sent: 20000, bounce_rate: 0.004, complaint_rate: 0.0001 })],
    isps: [],
    isp_shared_domains: [],
    isp_withheld_domains: [],
    email_sending_suspended: false,
    email_sending_suspended_at: null,
    email_sending_suspension_reason: '',
    sending_allowance: null,
}

function provider(isp: string, bounce_rate: number): IspSendingHealthApi {
    return {
        isp,
        emails_sent: 5000,
        delivery_rate: 0.95,
        bounce_rate,
        transient_bounce_rate: 0.01,
        complaint_rate: null,
        complaint_base: 0,
        unavailable: [],
    }
}

function setActionListFlag(on: boolean): void {
    act(() => {
        featureFlagLogic.actions.setFeatureFlags(on ? [FEATURE_FLAGS.WORKFLOWS_REPUTATION_ACTION_LIST] : [], {
            [FEATURE_FLAGS.WORKFLOWS_REPUTATION_ACTION_LIST]: on,
        })
    })
}

describe('ReputationTab', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/reputation': RESPONSE } })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { flag: false, shown: 'Project email sending health', hidden: 'Improve your sending reputation' },
        { flag: true, shown: 'Improve your sending reputation', hidden: 'Project email sending health' },
    ])('with the action list flag $flag renders "$shown"', async ({ flag, shown, hidden }) => {
        setActionListFlag(flag)
        render(
            <Provider>
                <ReputationTab />
            </Provider>
        )

        expect(await screen.findByText(shown)).toBeInTheDocument()
        expect(screen.queryByText(hidden)).not.toBeInTheDocument()
    })

    it.each([
        { case: 'provider rows', isps: [provider('Gmail', 0.004)], withheld: [], tab: true, marker: null },
        { case: 'only withheld domains', isps: [], withheld: ['mail.example.com'], tab: true, marker: null },
        { case: 'no provider data', isps: [], withheld: [], tab: false, marker: null },
        {
            case: 'a provider over the bounce line',
            isps: [provider('Gmail', 0.004), provider('Yahoo', 0.06)],
            withheld: [],
            tab: true,
            marker: '1 bounce warning',
        },
    ])('with $case, the provider tab shown is $tab', async ({ isps, withheld, tab, marker }) => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/reputation': {
                    ...RESPONSE,
                    isps,
                    isp_withheld_domains: withheld,
                },
            },
        })
        setActionListFlag(true)
        render(
            <Provider>
                <ReputationTab />
            </Provider>
        )

        expect(await screen.findByText('Improve your sending reputation')).toBeInTheDocument()
        expect(!!screen.queryByText('By mailbox provider')).toBe(tab)
        // pluralize joins the count with a non-breaking space.
        expect(screen.queryByText(/bounce warning/)?.textContent?.replace(/\s/g, ' ') ?? null).toEqual(marker)
    })
})
