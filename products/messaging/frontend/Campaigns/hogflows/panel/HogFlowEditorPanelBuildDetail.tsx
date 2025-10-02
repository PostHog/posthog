import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCollapse, LemonDivider, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { urls } from 'scenes/urls'

import { CategorySelect } from 'products/messaging/frontend/OptOuts/CategorySelect'

import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isOptOutEligibleAction } from '../steps/types'
import { HogFlowAction } from '../types'

export function HogFlowEditorPanelBuildDetail(): JSX.Element | null {
    const { selectedNode, categories, categoriesLoading } = useValues(hogFlowEditorLogic)
    const { setCampaignAction } = useActions(hogFlowEditorLogic)

    const Step = useHogFlowStep(selectedNode?.data)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data

    const actionFilters = action.filters ?? {}
    const numberOfActionFilters =
        (actionFilters.events?.length ?? 0) +
        (actionFilters.properties?.length ?? 0) +
        (actionFilters.actions?.length ?? 0)

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="flex flex-col gap-2 p-3"
                styledScrollbars
            >
                {Step?.renderConfiguration(selectedNode)}
            </ScrollableShadows>

            {isOptOutEligibleAction(action) && (
                <>
                    <LemonDivider className="my-0" />
                    <div className="flex flex-col px-2 py-1">
                        <LemonLabel htmlFor="Message category" className="flex gap-2 justify-between items-center">
                            <span>Message category</span>
                            <div className="flex gap-2">
                                {!categoriesLoading && !categories.length && (
                                    <LemonButton
                                        to={urls.messaging('opt-outs')}
                                        targetBlank
                                        type="secondary"
                                        icon={<IconExternal />}
                                    >
                                        Configure
                                    </LemonButton>
                                )}
                                <CategorySelect
                                    onChange={(categoryId) => {
                                        setCampaignAction(action.id, {
                                            ...action,
                                            config: {
                                                ...action.config,
                                                message_category_id: categoryId,
                                            },
                                        } as Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }>)
                                    }}
                                    value={action.config.message_category_id}
                                />
                            </div>
                        </LemonLabel>
                    </div>
                </>
            )}

            {!['trigger', 'exit'].includes(action.type) && (
                <>
                    <LemonDivider className="my-0" />

                    <div className="flex-0">
                        <LemonCollapse
                            embedded
                            panels={[
                                {
                                    key: 'filters',
                                    header: {
                                        children: (
                                            <>
                                                <span className="flex-1">Conditions</span>
                                                <LemonBadge.Number count={numberOfActionFilters} showZero={false} />
                                            </>
                                        ),
                                    },
                                    content: (
                                        <div>
                                            <>
                                                <p className="mb-0">
                                                    Add conditions to the step. If these conditions aren't met, the user
                                                    will skip this step and continue to the next one.
                                                </p>
                                                <HogFlowPropertyFilters
                                                    actionId={action.id}
                                                    filters={action.filters ?? {}}
                                                    setFilters={(filters) =>
                                                        setCampaignAction(action.id, { ...action, filters })
                                                    }
                                                    buttonCopy="Add filter conditions"
                                                />
                                            </>
                                        </div>
                                    ),
                                },
                                {
                                    key: 'on_error',
                                    header: {
                                        children: (
                                            <>
                                                <span className="flex-1">Error handling</span>
                                            </>
                                        ),
                                    },
                                    content: (
                                        <div>
                                            <>
                                                <p>
                                                    What to do if this step fails (e.g. message could not be sent). By
                                                    default, the user will continue to the next step.
                                                </p>
                                                <LemonSelect
                                                    options={[
                                                        { value: 'continue', label: 'Continue to next step' },
                                                        { value: 'abort', label: 'Exit the campaign' },
                                                    ]}
                                                    value={action.on_error || 'continue'}
                                                    onChange={(value) =>
                                                        setCampaignAction(action.id, {
                                                            ...action,
                                                            on_error: value,
                                                        })
                                                    }
                                                />
                                            </>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                </>
            )}
        </div>
    )
}
