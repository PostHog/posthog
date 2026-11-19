import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonBanner, LemonSkeleton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ReputationActionList } from './ReputationActionList'
import { BREAKDOWN_ELEMENT_ID, reputationActionListLogic } from './reputationActionListLogic'
import { ReputationNoEmailState } from './ReputationNoEmailState'
import { ReputationProviderBreakdown } from './ReputationProviderBreakdown'
import { reputationResponseLogic } from './reputationResponseLogic'
import { ReputationStatusStrip } from './ReputationStatusStrip'
import { reputationWorkflowSearchLogic } from './reputationWorkflowSearchLogic'
import { ReputationWorkflowTable } from './ReputationWorkflowTable'

// PROTOTYPE: `top` holds variant B's warm-up card and paused banner, which replace the strip's
// allowance and the page's own paused banner.
export function WorkflowsReputationActions({ top }: { top: ReactNode }): JSX.Element {
    const {
        reputationResponse,
        reputationResponseLoading,
        reputationLoadError,
        hasSendingData,
        ispSendingHealth,
        ispWithheldDomains,
    } = useValues(reputationResponseLogic)
    const { loadReputation } = useActions(reputationResponseLogic)
    const { activeBreakdownTab, providersOverLineCount } = useValues(reputationActionListLogic)
    const { setActiveBreakdownTab } = useActions(reputationActionListLogic)
    // The tabs unmount the table they hide, so the page keeps the search mounted across tab switches.
    useMountedLogic(reputationWorkflowSearchLogic)
    const hasProviderBreakdown = ispSendingHealth.length > 0 || ispWithheldDomains.length > 0

    return (
        <div className="space-y-4" data-attr="workflows-reputation">
            {top}
            {!reputationResponse && reputationResponseLoading ? (
                <div className="space-y-4" data-attr="workflows-reputation-loading">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-48" />
                    <LemonSkeleton className="h-64" />
                </div>
            ) : !reputationResponse && reputationLoadError === 'forbidden' ? (
                <div data-attr="workflows-reputation-load-forbidden">
                    <LemonBanner type="warning">
                        You don't have access to this project's sending reputation. Ask a project admin for access to
                        workflows.
                    </LemonBanner>
                </div>
            ) : !reputationResponse && reputationLoadError ? (
                <div data-attr="workflows-reputation-load-error">
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadReputation }}>
                        Couldn't load your sending reputation. Try again, and if it keeps happening, contact support.
                    </LemonBanner>
                </div>
            ) : !hasSendingData ? (
                <ReputationNoEmailState />
            ) : (
                <>
                    <ReputationActionList />
                    <ReputationStatusStrip />
                    <div id={BREAKDOWN_ELEMENT_ID} data-attr="workflows-reputation-breakdown">
                        {hasProviderBreakdown ? (
                            <LemonTabs
                                activeKey={activeBreakdownTab}
                                onChange={setActiveBreakdownTab}
                                data-attr="workflows-reputation-breakdown-tabs"
                                tabs={[
                                    { key: 'workflows', label: 'By workflow', content: <ReputationWorkflowTable /> },
                                    {
                                        key: 'providers',
                                        label: (
                                            <>
                                                By mailbox provider
                                                {providersOverLineCount > 0 && (
                                                    <LemonTag type="warning" size="small" className="ml-1">
                                                        {pluralize(providersOverLineCount, 'bounce warning')}
                                                    </LemonTag>
                                                )}
                                            </>
                                        ),
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
                    </div>
                </>
            )}
        </div>
    )
}
