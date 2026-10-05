import { useState } from 'react'

import { Button, ItemRadio, MenuLabel, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { SHEET_PARTS } from '~/layout/today/todayMenuParts'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { TodaySheetSub } from '~/layout/today/TodaySheetSub'

import {
    type ComposerEffortOption,
    getEffortLabel,
    getHarnessLabel,
} from 'products/posthog_ai/frontend/utils/composerModels'
import {
    ModelAccessEnumApi,
    ModelChoiceApi,
    ReasoningEffortEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { ModelCostChip } from '../ModelCostChip'
import { ModelCostFooter } from '../ModelCostFooter'
import type { ComposerCodexBilling } from './ComposerModelEffortPickers'

export interface ComposerModelEffortSheetProps {
    modelLabel: string
    selectedModel: string
    selectedEffort: ReasoningEffortEnumApi
    selectedAdapter: string
    adapters: string[]
    adapterModels: ModelChoiceApi[]
    effortOptions: ComposerEffortOption[]
    showsAnyCost: boolean
    harnessDisabled: (adapter: string) => boolean
    billing?: ComposerCodexBilling
    billingLabels: Record<ModelAccessEnumApi, string>
    onModelChange: (model: string) => void
    onEffortChange: (effort: ReasoningEffortEnumApi) => void
    onAdapterChange: (adapter: string) => void
    resetDisabled: boolean
    onReset?: () => void
    onOpenDefaultSettings?: () => void
}

export function ComposerModelEffortSheet({
    modelLabel,
    selectedModel,
    selectedEffort,
    selectedAdapter,
    adapters,
    adapterModels,
    effortOptions,
    showsAnyCost,
    harnessDisabled,
    billing,
    billingLabels,
    onModelChange,
    onEffortChange,
    onAdapterChange,
    resetDisabled,
    onReset,
    onOpenDefaultSettings,
}: ComposerModelEffortSheetProps): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <>
            <Button size="lg" onClick={() => setOpen(true)} data-attr="composer-model-sheet-open">
                <span className="max-w-32 truncate">{modelLabel}</span>
                {effortOptions.length > 0 && <span className="text-muted">{getEffortLabel(selectedEffort)}</span>}
                {billing?.value === ModelAccessEnumApi.OwnSubscription && (
                    <span className="text-muted">ChatGPT plan</span>
                )}
            </Button>
            <TodaySheetMenu open={open} onOpenChange={setOpen} title="Model and reasoning">
                {effortOptions.length > 0 && (
                    <div className="flex flex-col gap-2 px-3 pt-1 pb-3">
                        <MenuLabel className="px-0">Reasoning</MenuLabel>
                        <ToggleGroup
                            variant="outline"
                            value={[selectedEffort]}
                            onValueChange={(value: string[]) =>
                                value[0] && onEffortChange(value[0] as ReasoningEffortEnumApi)
                            }
                            aria-label="Reasoning"
                            spacing={1}
                            className="grid w-full grid-cols-3"
                        >
                            {effortOptions.map((option) => (
                                <ToggleGroupItem
                                    key={option.value}
                                    value={option.value}
                                    className="w-full"
                                    data-attr="composer-model-sheet-effort"
                                >
                                    {option.label}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </div>
                )}
                <MenuLabel className="px-3">Model</MenuLabel>
                <div role="radiogroup" aria-label="Model" className="flex flex-col">
                    {adapterModels.map((option) => {
                        const selected = option.model === selectedModel
                        return (
                            <ItemRadio
                                key={option.model}
                                aria-checked={selected}
                                className="flex-nowrap"
                                onClick={() => onModelChange(option.model)}
                                data-attr="composer-model-sheet-model"
                            >
                                <span className="min-w-0 flex-1 truncate text-left">{option.display_name}</span>
                                <ModelCostChip model={option.model} />
                            </ItemRadio>
                        )
                    })}
                </div>
                {showsAnyCost && (
                    <div className="px-1">
                        <ModelCostFooter />
                    </div>
                )}
                {(adapters.length > 1 || billing) && <SHEET_PARTS.Separator />}
                {adapters.length > 1 && (
                    <TodaySheetSub
                        label="Harness"
                        title="Harness"
                        value={getHarnessLabel(selectedAdapter)}
                        dataAttr="composer-model-sheet-harness"
                    >
                        {adapters.map((adapter) => (
                            <ItemRadio
                                key={adapter}
                                aria-checked={adapter === selectedAdapter}
                                disabled={harnessDisabled(adapter)}
                                onClick={() => {
                                    onAdapterChange(adapter)
                                    setOpen(false)
                                }}
                                data-attr={`composer-model-sheet-harness-${adapter}`}
                            >
                                {getHarnessLabel(adapter)}
                            </ItemRadio>
                        ))}
                    </TodaySheetSub>
                )}
                {billing && (
                    <TodaySheetSub
                        label="Billing"
                        title="Billing"
                        value={billingLabels[billing.value]}
                        dataAttr="composer-model-sheet-billing"
                    >
                        {[ModelAccessEnumApi.PosthogGateway, ModelAccessEnumApi.OwnSubscription].map((value) => (
                            <ItemRadio
                                key={value}
                                aria-checked={value === billing.value}
                                disabled={
                                    billing.locked ||
                                    (value === ModelAccessEnumApi.OwnSubscription && !billing.planConnected)
                                }
                                onClick={() => {
                                    billing.onChange(value)
                                    setOpen(false)
                                }}
                                data-attr={`composer-model-sheet-billing-${value}`}
                            >
                                {billingLabels[value]}
                            </ItemRadio>
                        ))}
                        {!billing.planConnected && !billing.locked && (
                            <>
                                <SHEET_PARTS.Separator />
                                <SHEET_PARTS.Item
                                    onClick={billing.onConnectPlan}
                                    dataAttr="composer-codex-connect-plan"
                                >
                                    Connect your ChatGPT account
                                </SHEET_PARTS.Item>
                            </>
                        )}
                    </TodaySheetSub>
                )}
                {(onReset || onOpenDefaultSettings) && <SHEET_PARTS.Separator />}
                {onReset && (
                    <SHEET_PARTS.Item disabled={resetDisabled} onClick={onReset} dataAttr="composer-model-sheet-reset">
                        Reset to default
                    </SHEET_PARTS.Item>
                )}
                {onOpenDefaultSettings && (
                    <SHEET_PARTS.Item onClick={onOpenDefaultSettings} dataAttr="composer-model-sheet-change-default">
                        Change default
                    </SHEET_PARTS.Item>
                )}
            </TodaySheetMenu>
        </>
    )
}
