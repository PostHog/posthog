import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { urls } from 'scenes/urls'

import { CategorySelect } from '../../OptOuts/CategorySelect'
import { HogFlowFilters } from './filters/HogFlowFilters'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { isOptOutEligibleAction } from './steps/types'
import { HogFlowAction } from './types'

export function HogFlowEditorDetailsPanel(): JSX.Element | null {
    const { selectedNode, categories, categoriesLoading } = useValues(hogFlowEditorLogic)
    const { setCampaignAction } = useActions(hogFlowEditorLogic)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data
    const Step = getHogFlowStep(action.type)

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
                    <div className="flex flex-col p-2">
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
                    <div className="flex flex-col p-2">
                        <LemonLabel htmlFor="conditions" className="flex gap-2 justify-between items-center">
                            <span>Conditions</span>
                            <LemonSwitch
                                id="conditions"
                                checked={!!action.filters}
                                onChange={(checked) =>
                                    setCampaignAction(action.id, {
                                        ...action,
                                        filters: checked ? {} : null,
                                    })
                                }
                            />
                        </LemonLabel>

                        {action.filters && (
                            <>
                                <p className="mb-0">
                                    Add conditions to the step. If these conditions aren't met, the user will skip this
                                    step and continue to the next one.
                                </p>
                                <HogFlowFilters
                                    filters={action.filters ?? {}}
                                    setFilters={(filters) => setCampaignAction(action.id, { ...action, filters })}
                                    buttonCopy="Add filter conditions"
                                />
                            </>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}
