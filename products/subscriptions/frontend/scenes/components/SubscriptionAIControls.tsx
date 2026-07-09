import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonDialog, LemonDivider } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { subscriptionSceneLogic, substituteWindowPlaceholders } from '../subscriptionSceneLogic'
import type { QueryPlanStep } from '../subscriptionSceneLogic'

/** View + edit the frozen query plan: each step's description (read-only) and HogQL (editable, with
 * Monaco HogQL highlighting; validation runs against a placeholder-substituted copy of the text). */
function FrozenQueryPlanEditor({ steps }: { steps: QueryPlanStep[] }): JSX.Element {
    const { queryPlanEdits, hasQueryPlanEdits, subscriptionLoading } = useValues(subscriptionSceneLogic)
    const { setQueryPlanStepHogql, resetQueryPlanEdits, saveQueryPlan } = useActions(subscriptionSceneLogic)

    return (
        <div className="flex flex-col gap-3">
            <LemonCollapse
                size="small"
                multiple
                panels={steps.map((step, index) => {
                    const hogql = queryPlanEdits[index] ?? step.hogql
                    return {
                        key: index,
                        header: <span>{step.description || `Query ${index + 1}`}</span>,
                        content: (
                            <div data-attr={`subscription-query-plan-step-${index}`}>
                                <CodeEditorInline
                                    language="hogQL"
                                    queryKey={`subscription-query-plan-step-${index}`}
                                    value={hogql}
                                    onChange={(value) => setQueryPlanStepHogql(index, value ?? '')}
                                    metadataQuery={substituteWindowPlaceholders(hogql)}
                                    minHeight="80px"
                                    maxHeight="400px"
                                    options={{
                                        ariaLabel: `HogQL for step ${index + 1}: ${step.description || 'query'}`,
                                    }}
                                />
                            </div>
                        ),
                    }
                })}
            />
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={saveQueryPlan}
                    loading={subscriptionLoading}
                    disabledReason={
                        !hasQueryPlanEdits ? 'Edit a query to enable saving' : subscriptionLoading ? 'Saving…' : null
                    }
                    data-attr="subscription-save-query-plan"
                >
                    Save plan
                </LemonButton>
                {hasQueryPlanEdits ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={resetQueryPlanEdits}
                        disabled={subscriptionLoading}
                    >
                        Discard edits
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}

/**
 * Owner controls for an AI (prompt) subscription's frozen query plan: regenerate the plan from the
 * prompt (clearing the frozen one) and view/edit the frozen queries. Verify changes with a test
 * delivery — the report (and its generated queries) lands in the delivery history below.
 */
export function SubscriptionAIControls(): JSX.Element {
    const { subscription, subscriptionLoading } = useValues(subscriptionSceneLogic)
    const { regeneratePlan } = useActions(subscriptionSceneLogic)

    const steps = subscription?.ai_query_plan?.steps ?? []

    const confirmRegenerate = (): void => {
        LemonDialog.open({
            title: 'Regenerate the query plan?',
            description:
                'This clears the frozen query plan, so the next report re-plans from your prompt and freezes a fresh plan. Any edits you made to the queries will be discarded.',
            primaryButton: {
                children: 'Regenerate plan',
                status: 'danger',
                onClick: () => regeneratePlan(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-lg font-semibold">AI report plan</h2>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={confirmRegenerate}
                            loading={subscriptionLoading}
                            disabledReason={subscriptionLoading ? 'Working…' : null}
                            data-attr="subscription-regenerate-plan"
                        >
                            Regenerate plan
                        </LemonButton>
                    </div>
                </div>
                <p className="text-sm text-secondary m-0">
                    Regenerate plan discards the frozen plan so the next report is planned fresh from your prompt. Use a
                    test delivery to see the resulting report — it sends to the configured recipients and appears in the
                    history below with its generated queries.
                </p>
                {steps.length > 0 ? (
                    <div className="flex flex-col gap-2">
                        <div className="text-xs font-semibold uppercase tracking-wide text-secondary">
                            Frozen queries
                        </div>
                        <FrozenQueryPlanEditor steps={steps} />
                    </div>
                ) : (
                    <p className="text-sm text-secondary m-0">
                        No frozen plan yet — it is created on the first delivery. Send a test delivery to generate one.
                    </p>
                )}
            </div>
        </>
    )
}
