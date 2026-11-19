import { BindLogic, useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSwitch } from '@posthog/lemon-ui'

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
    const { tab, transactionalHogFlowId, savedVariables, hasChanges, template, templateLoading } = useValues(
        transactionalPushLogic({ id })
    )
    const { setTab, makeTransactional, setSensitive } = useActions(transactionalPushLogic({ id }))

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
                        <div className="flex flex-col gap-4">
                            <LemonCard hoverEffect={false} className="max-w-200 p-4">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex items-start gap-3 min-w-0">
                                        <IconLock className="text-xl text-secondary shrink-0 mt-0.5" />
                                        <div className="min-w-0">
                                            <div className="font-semibold">Protect sensitive data</div>
                                            <p className="text-secondary text-sm m-0 mt-1">
                                                For push notifications with login codes or reset links. PostHog keeps no
                                                copy of what each notification contained.
                                            </p>
                                        </div>
                                    </div>
                                    <LemonSwitch
                                        checked={!!template?.sensitive}
                                        onChange={setSensitive}
                                        loading={templateLoading}
                                        disabledReason={
                                            editDisabledReason ?? (templateLoading ? 'Saving the setting' : undefined)
                                        }
                                        aria-label="Protect sensitive data"
                                        data-attr="transactional-push-sensitive-toggle"
                                    />
                                </div>
                            </LemonCard>
                            <TransactionalPushApiExample templateId={id} variables={savedVariables} />
                        </div>
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
