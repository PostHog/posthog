import type { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Field, FieldTitle, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { FunnelStepOrderPicker } from 'products/product_analytics/frontend/insights/funnels/filters/FunnelStepOrderPicker'

import { FunnelExclusionsFilter } from '../filters/FunnelExclusionsFilter/FunnelExclusionsFilter'
import { FunnelStepReferencePicker } from '../filters/FunnelStepReferencePicker'

export interface QuillFunnelsAdvancedProps {
    stepOrderInfo: ReactNode
    exclusionStepsInfo: ReactNode
    showReset: boolean
    onReset: () => void
}

export function QuillFunnelsAdvanced({
    stepOrderInfo,
    exclusionStepsInfo,
    showReset,
    onReset,
}: QuillFunnelsAdvancedProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <AdvancedField label="Step order" info={stepOrderInfo}>
                <FunnelStepOrderPicker />
            </AdvancedField>
            <AdvancedField label="Conversion rate calculation">
                <FunnelStepReferencePicker />
            </AdvancedField>
            <AdvancedField label="Exclusion steps" info={exclusionStepsInfo}>
                <FunnelExclusionsFilter />
            </AdvancedField>
            {showReset && (
                <Button variant="destructive-outline" className="self-start" onClick={onReset}>
                    Reset advanced options
                </Button>
            )}
        </div>
    )
}

function AdvancedField({
    label,
    info,
    children,
}: {
    label: string
    info?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <Field className="min-w-0 gap-1.5">
            <FieldTitle className="flex items-center gap-1">
                {label}
                {info && (
                    <Tooltip>
                        <TooltipTrigger
                            render={<span className="inline-flex text-muted-foreground" />}
                            aria-label="More info"
                        >
                            <IconInfo className="size-4" />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">{info}</TooltipContent>
                    </Tooltip>
                )}
            </FieldTitle>
            {children}
        </Field>
    )
}
