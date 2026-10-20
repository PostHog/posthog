import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Button, Field, FieldTitle, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { EditorFilterProps } from '~/types'

import { FunnelStepOrderPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelStepOrderPicker'
import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'

function InfoTooltip({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}>
                <IconInfo className="size-4 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{children}</TooltipContent>
        </Tooltip>
    )
}

export function QuillFunnelsAdvanced({ insightProps }: EditorFilterProps): JSX.Element {
    const { querySource, aggregationTargetLabel, advancedOptionsUsedCount } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <div className="flex flex-col gap-4">
            <Field>
                <FieldTitle>
                    Step order
                    <InfoTooltip>
                        <ul className="list-disc pl-4">
                            <li>
                                <b>Sequential</b> - Step B must happen after Step A, but any number events can happen
                                between A and B.
                            </li>
                            <li>
                                <b>Strict order</b> - Step B must happen directly after Step A without any events in
                                between.
                            </li>
                            <li>
                                <b>Any order</b> - Steps can be completed in any sequence.
                            </li>
                        </ul>
                    </InfoTooltip>
                </FieldTitle>
                <FunnelStepOrderPicker />
            </Field>
            <Field>
                <FieldTitle>Conversion rate calculation</FieldTitle>
                <FunnelStepReferencePicker />
            </Field>
            <Field>
                <FieldTitle>
                    Exclusion steps
                    <InfoTooltip>
                        Exclude {aggregationTargetLabel.plural}{' '}
                        {querySource?.aggregation_group_type_index != null ? 'that' : 'who'} completed the specified
                        event between two specific steps. Note that these {aggregationTargetLabel.plural} will be{' '}
                        <b>completely excluded from the entire funnel</b>.
                    </InfoTooltip>
                </FieldTitle>
                <FunnelExclusionsFilter />
            </Field>
            {!!advancedOptionsUsedCount && (
                <div>
                    <Button
                        variant="destructive"
                        onClick={() =>
                            updateInsightFilter({
                                funnelOrderType: undefined,
                                funnelStepReference: undefined,
                                exclusions: undefined,
                            })
                        }
                    >
                        Reset advanced options
                    </Button>
                </div>
            )}
        </div>
    )
}
