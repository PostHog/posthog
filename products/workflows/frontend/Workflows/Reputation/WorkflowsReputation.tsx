import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import { ReputationActionList } from './ReputationActionList'
import { ReputationNoEmailState } from './ReputationNoEmailState'
import { ReputationProviderBreakdown } from './ReputationProviderBreakdown'
import { ReputationStatusStrip } from './ReputationStatusStrip'
import { ReputationWorkflowTable } from './ReputationWorkflowTable'
import { workflowsReputationLogic } from './workflowsReputationLogic'

export function WorkflowsReputation(): JSX.Element {
    const {
        awsReputation,
        reputationResponse,
        reputationResponseLoading,
        reputationLoadError,
        hasSendingData,
        ispSendingHealth,
        ispWithheldDomains,
        activeBreakdownTab,
    } = useValues(workflowsReputationLogic)
    const { loadReputation, setActiveBreakdownTab } = useActions(workflowsReputationLogic)
    const hasProviderBreakdown = ispSendingHealth.length > 0 || ispWithheldDomains.length > 0

    return (
        <div className="space-y-4" data-attr="workflows-reputation">
            {awsReputation?.sending_status === 'DISABLED' && (
                <LemonBanner type="error" data-attr="workflows-reputation-disabled-banner">
                    {awsReputation.findings.length > 0
                        ? 'Email sending is paused for this project because of reputation problems. Fix the open findings below, then contact support to get sending re-enabled.'
                        : 'Email sending is paused for this project. Contact support to get sending re-enabled.'}
                </LemonBanner>
            )}
            {!reputationResponse && reputationResponseLoading ? (
                <div className="space-y-4" data-attr="workflows-reputation-loading">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-48" />
                    <LemonSkeleton className="h-64" />
                </div>
            ) : !reputationResponse && reputationLoadError === 'forbidden' ? (
                <LemonBanner type="warning" data-attr="workflows-reputation-load-forbidden">
                    You don't have access to this project's sending reputation. Ask a project admin for access to
                    workflows.
                </LemonBanner>
            ) : !reputationResponse && reputationLoadError ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadReputation }}
                    data-attr="workflows-reputation-load-error"
                >
                    Couldn't load your sending reputation. Try again, and if it keeps happening, contact support.
                </LemonBanner>
            ) : !hasSendingData ? (
                <ReputationNoEmailState />
            ) : (
                <>
                    <ReputationStatusStrip />
                    <ReputationActionList />
                    {hasProviderBreakdown ? (
                        <LemonTabs
                            activeKey={activeBreakdownTab}
                            onChange={setActiveBreakdownTab}
                            data-attr="workflows-reputation-breakdown-tabs"
                            tabs={[
                                { key: 'workflows', label: 'By workflow', content: <ReputationWorkflowTable /> },
                                {
                                    key: 'providers',
                                    label: 'By mailbox provider',
                                    content: <ReputationProviderBreakdown />,
                                },
                            ]}
                        />
                    ) : (
                        <div className="space-y-2">
                            <h2 className="text-base font-semibold mb-0">By workflow</h2>
                            <ReputationWorkflowTable />
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
