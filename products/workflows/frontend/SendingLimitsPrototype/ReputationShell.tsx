// PROTOTYPE (branch prototype/sending-limits-ux): mounts the real Reputation page with fake data and
// swaps its allowance card and banners for the variant's, never merge.
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

import { WorkflowsReputation, sendingLimitsPrototypeSlot } from '../Workflows/Reputation/WorkflowsReputation'
import { workflowsReputationLogic } from '../Workflows/Reputation/workflowsReputationLogic'
import { SendingState } from './sendingLimitsPrototypeData'

let currentResponse: TeamEmailReputationResponseApi | null = null

export function reputationResponseFor(state: SendingState): TeamEmailReputationResponseApi {
    const blocked = state.key === 'blocked'
    return {
        aws: {
            health: blocked ? 'suspended' : state.key === 'moved-down' ? 'warning' : 'healthy',
            sending_status: blocked ? 'DISABLED' : 'ENABLED',
            findings: blocked
                ? [
                      {
                          finding_type: 'COMPLAINT',
                          impact: 'HIGH',
                          description: 'Spam complaints are above the limit for this sender.',
                          last_updated_at: '2026-12-09T08:00:00Z',
                      },
                  ]
                : state.rates30d.sent > 0
                  ? [
                        {
                            finding_type: 'BIMI',
                            impact: 'LOW',
                            description: 'No BIMI record, so inboxes show no brand logo.',
                            last_updated_at: '2026-12-01T08:00:00Z',
                        },
                    ]
                  : [],
        },
        reputation:
            state.rates30d.sent > 0
                ? {
                      bounce_rate: state.rates30d.bounce,
                      complaint_rate: state.rates30d.complaint,
                      emails_sent: state.rates30d.sent,
                  }
                : null,
        workflows:
            state.rates30d.sent > 0
                ? [
                      {
                          hog_flow_id: '0199c0de-0000-7000-8000-000000000001',
                          hog_flow_name: state.key === 'moved-down' ? 'Product updates' : state.broadcast.name,
                          emails_sent: Math.round(state.rates30d.sent * 0.6),
                          bounce_rate: state.rates30d.bounce * 1.4,
                          complaint_rate: state.rates30d.complaint,
                          email_sending_paused: false,
                          email_sending_paused_at: null,
                          email_sending_paused_reason: '',
                      },
                      ...(state.key === 'moved-down'
                          ? [
                                {
                                    hog_flow_id: '0199c0de-0000-7000-8000-000000000003',
                                    hog_flow_name: 'Win back old trials',
                                    emails_sent: 450,
                                    bounce_rate: 0.071,
                                    complaint_rate: 0,
                                    email_sending_paused: false,
                                    email_sending_paused_at: null,
                                    email_sending_paused_reason: '',
                                },
                            ]
                          : []),
                      {
                          hog_flow_id: '0199c0de-0000-7000-8000-000000000002',
                          hog_flow_name: 'Welcome series',
                          emails_sent: Math.round(state.rates30d.sent * 0.4),
                          bounce_rate: state.rates30d.bounce * 0.4,
                          complaint_rate: state.rates30d.complaint,
                          email_sending_paused: false,
                          email_sending_paused_at: null,
                          email_sending_paused_reason: '',
                      },
                  ]
                : [],
        isps:
            state.rates30d.sent > 0
                ? [
                      ['Gmail', 0.45],
                      ['Microsoft', 0.3],
                      ['Yahoo', 0.15],
                      ['Apple', 0.1],
                  ].map(([isp, share]) => ({
                      isp: isp as string,
                      emails_sent: Math.round(state.rates30d.sent * (share as number)),
                      delivery_rate: 1 - state.rates30d.bounce,
                      bounce_rate: isp === 'Microsoft' ? state.rates30d.bounce * 2 : state.rates30d.bounce * 0.7,
                      transient_bounce_rate: 0.004,
                      complaint_rate: isp === 'Apple' ? null : state.rates30d.complaint,
                      complaint_base: isp === 'Apple' ? 0 : Math.round(state.rates30d.sent * (share as number) * 0.9),
                      unavailable: [],
                  }))
                : [],
        isp_shared_domains: [],
        isp_withheld_domains: [],
        sending_allowance: {
            tier: 1,
            max_tier: 7,
            emails_per_day: Math.max(state.allowancePerDay, 100),
            max_batch_audience: Math.max(state.allowancePerDay, 100),
            rate_limited_max_batch_audience: null,
            emails_sent_last_day: state.sentToday,
            enforced: true,
        },
        email_sending_suspended: false,
        email_sending_suspended_at: null,
        email_sending_suspension_reason: '',
    } as TeamEmailReputationResponseApi
}

interface ReputationShellProps {
    renderKey: string
    state: SendingState
    allowance: (() => JSX.Element | null) | null
    banners?: (() => JSX.Element | null) | null
}

export function ReputationShell({ renderKey, state, allowance, banners = null }: ReputationShellProps): JSX.Element {
    currentResponse = reputationResponseFor(state)
    useStorybookMocks({ get: { '/api/projects/:team_id/hog_flows/reputation': () => [200, currentResponse] } })
    useMountedLogic(workflowsReputationLogic)
    const { loadReputationSuccess } = useActions(workflowsReputationLogic)
    useEffect(() => {
        loadReputationSuccess(reputationResponseFor(state))
    }, [renderKey]) // eslint-disable-line react-hooks/exhaustive-deps
    sendingLimitsPrototypeSlot.allowance = allowance
    sendingLimitsPrototypeSlot.banners = banners
    return <WorkflowsReputation key={renderKey} />
}
