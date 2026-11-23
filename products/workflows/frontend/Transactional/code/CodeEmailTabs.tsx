import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { WorkflowInvocations } from '../../Workflows/WorkflowInvocations'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowMetrics } from '../../Workflows/WorkflowMetrics'
import { impactTab } from '../impact/impactTab'
import { openEmailMetricSends } from '../log/emailMetricSends'
import { TransactionalEmailLog } from '../log/TransactionalEmailLog'
import { CodeEmailApiExample } from './CodeEmailApiExample'
import { codeEmailLogic } from './codeEmailLogic'

export function CodeEmailTabs({ codeEmail }: { codeEmail: CodeEmailApi }): JSX.Element {
    const { tab } = useValues(codeEmailLogic)
    const { setTab, showRuns } = useActions(codeEmailLogic)
    const workflowProps = { id: codeEmail.hog_flow_id }
    const { originalWorkflow, workflowLoading } = useValues(workflowLogic(workflowProps))
    const { loadWorkflow } = useActions(workflowLogic(workflowProps))
    const sendLinks = useFeatureFlag('WORKFLOWS_EMAIL_SEND_LINKS')
    const impact = useFeatureFlag('WORKFLOWS_EMAIL_IMPACT')

    // Metrics and sends name each step from the workflow, so without it they would show an empty workflow.
    const workflowFailed = !originalWorkflow && !workflowLoading
    const failedBanner = (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: () => loadWorkflow(), 'data-attr': 'code-email-workflow-retry' }}
        >
            {sendLinks
                ? "This email's metrics and run logs couldn't load. Check your connection and try again."
                : "This email's metrics and sends couldn't load. Check your connection and try again."}
        </LemonBanner>
    )

    return (
        // The reused workflow tabs read workflowLogic without props, so bind it to this email's workflow.
        <BindLogic logic={workflowLogic} props={workflowProps}>
            <LemonTabs
                activeKey={!sendLinks && tab === 'sends' ? 'runs' : !impact && tab === 'impact' ? 'metrics' : tab}
                onChange={setTab}
                tabs={[
                    impact && impactTab(codeEmail.hog_flow_id),
                    {
                        key: 'metrics',
                        label: 'Metrics',
                        content: workflowFailed ? (
                            failedBanner
                        ) : (
                            <WorkflowMetrics
                                id={codeEmail.hog_flow_id}
                                {...(sendLinks
                                    ? { onEmailMetricClick: openEmailMetricSends }
                                    : { onShowInvocations: showRuns })}
                            />
                        ),
                    },
                    ...(sendLinks
                        ? [
                              {
                                  key: 'sends' as const,
                                  label: 'Sends',
                                  content: <TransactionalEmailLog workflowId={codeEmail.hog_flow_id} />,
                              },
                          ]
                        : []),
                    {
                        key: 'runs',
                        label: sendLinks ? 'Run logs' : 'Sends',
                        content: workflowFailed ? (
                            failedBanner
                        ) : (
                            <WorkflowInvocations
                                id={codeEmail.hog_flow_id}
                                linkSteps={false}
                                // A sensitive email's sends keep no content, so a re-run would send nothing.
                                rerunDisabledReason={
                                    codeEmail.sensitive
                                        ? "This email is sensitive, so its content isn't stored and can't be sent again"
                                        : undefined
                                }
                            />
                        ),
                    },
                    { key: 'api', label: 'API', content: <CodeEmailApiExample templateKey={codeEmail.key} /> },
                ]}
            />
        </BindLogic>
    )
}
