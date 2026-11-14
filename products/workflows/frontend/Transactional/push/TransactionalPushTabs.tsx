import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

import { WorkflowInvocations } from '../../Workflows/WorkflowInvocations'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowMetrics } from '../../Workflows/WorkflowMetrics'
import { WorkflowRevisions } from '../../Workflows/WorkflowRevisions'
import { TransactionalPushApiExample } from './TransactionalPushApiExample'
import { TransactionalPushEditor } from './TransactionalPushEditor'
import { transactionalPushLogic } from './transactionalPushLogic'

export function TransactionalPushTabs({
    id,
    editDisabledReason,
}: {
    id: string
    editDisabledReason: string | undefined
}): JSX.Element {
    const { tab, transactionalHogFlowId, savedVariables, hasChanges } = useValues(transactionalPushLogic({ id }))
    const { setTab, makeTransactional } = useActions(transactionalPushLogic({ id }))

    const workflowTabs = transactionalHogFlowId
        ? [
              { key: 'metrics' as const, label: 'Metrics', content: <WorkflowMetrics id={transactionalHogFlowId} /> },
              { key: 'sends' as const, label: 'Sends', content: <WorkflowInvocations id={transactionalHogFlowId} /> },
              {
                  key: 'versions' as const,
                  label: 'Versions',
                  content: <WorkflowRevisions id={transactionalHogFlowId} />,
              },
          ]
        : []
    const tabs = (
        <LemonTabs
            activeKey={tab}
            onChange={setTab}
            tabs={[
                { key: 'content', label: 'Content', content: <TransactionalPushEditor id={id} /> },
                ...workflowTabs,
                {
                    key: 'api',
                    label: 'API',
                    content: transactionalHogFlowId ? (
                        <TransactionalPushApiExample templateId={id} variables={savedVariables} />
                    ) : (
                        <LemonBanner
                            type="info"
                            action={{
                                children: 'Make sendable',
                                onClick: makeTransactional,
                                disabledReason:
                                    editDisabledReason ?? (hasChanges ? 'Publish your changes first' : undefined),
                                'data-attr': 'transactional-push-make-transactional',
                            }}
                        >
                            This push notification can't be sent over the API yet.
                        </LemonBanner>
                    ),
                },
            ]}
        />
    )

    // The workflow tabs read workflowLogic without props, so it is bound to this push's workflow.
    return transactionalHogFlowId ? (
        <BindLogic logic={workflowLogic} props={{ id: transactionalHogFlowId }}>
            {tabs}
        </BindLogic>
    ) : (
        tabs
    )
}
