import { useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import {
    getEffortLabel,
    getEffortsForModel,
    getModelLabel,
    getRuntimeAdapterForModel,
    getRuntimeAdapterLabel,
    listRuntimeAdapters,
    modelsForRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModels'
import {
    ModelChoiceApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

export interface ComposerModelEffortPickersProps {
    /** Models to offer, and the efforts each supports. Callers pass `modelCatalogueLogic`'s live catalogue. */
    models: ModelChoiceApi[]
    selectedModel: string
    selectedEffort: ReasoningEffortEnumApi
    onModelChange: (model: string) => void
    onEffortChange: (effort: ReasoningEffortEnumApi) => void
    /**
     * The harness a live run already booted, if any. A running sandbox is one agent binary, and the mid-run config
     * channel only carries model/effort — so the other harnesses can't be reached without starting a new run, and are
     * offered as disabled. `null`/omitted means nothing is running and every harness is selectable.
     */
    lockedRuntimeAdapter?: string | null
}

/**
 * Controlled, logic-free model + reasoning-effort picker for a composer footer. The caller owns the selection and the
 * side effects of changing it — the run composer wires it to `runInteractionLogic` (held client-side and applied at
 * send time), the new-task composer wires it to the form that seeds the first run.
 *
 * Laid out as one chip opening a Harness → Model → Reasoning cascade, mirroring the desktop app's advanced view so the
 * two surfaces read the same. Every option comes from the passed catalogue; nothing about a specific model is
 * hardcoded here.
 */
interface PickerSectionProps {
    title: string
    /** Right-aligned summary on the closed row — the value this section currently holds. */
    current: string
    value: string
    onValueChange: (value: string) => void
    children: React.ReactNode
}

/** One `label … current ›` row of the cascade, opening a radio list. */
function PickerSection({ title, current, value, onValueChange, children }: PickerSectionProps): JSX.Element {
    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger>
                <span>{title}</span>
                <span className="flex-1 text-right text-muted">{current}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuRadioGroup value={value} onValueChange={onValueChange}>
                    {children}
                </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

export function ComposerModelEffortPickers({
    models,
    selectedModel,
    selectedEffort,
    onModelChange,
    onEffortChange,
    lockedRuntimeAdapter,
}: ComposerModelEffortPickersProps): JSX.Element {
    const [open, setOpen] = useState(false)

    // The catalogue only changes when the gateway list reloads, so derive the whole tree in one pass — this
    // component re-renders on every keystroke in the composer above it.
    const { selectedAdapter, modelLabel, effortOptions, adapters, adapterModels } = useMemo(() => {
        const adapter = getRuntimeAdapterForModel(models, selectedModel)
        return {
            selectedAdapter: adapter,
            modelLabel: getModelLabel(models, selectedModel),
            effortOptions: getEffortsForModel(models, selectedModel),
            adapters: listRuntimeAdapters(models),
            adapterModels: modelsForRuntimeAdapter(models, adapter),
        }
    }, [models, selectedModel])

    // Switching harness picks that harness's first model; the caller clamps the effort to one it supports.
    const selectAdapter = (adapter: string): void => {
        const runtimeAdapter = adapter as RuntimeAdapterEnumApi
        const first = modelsForRuntimeAdapter(models, runtimeAdapter)[0]
        if (first && first.model !== selectedModel) {
            onModelChange(first.model)
        }
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <Button variant="outline" size="sm">
                        {modelLabel}
                        {effortOptions.length > 0 && (
                            <span className="text-muted">{getEffortLabel(selectedEffort)}</span>
                        )}
                        <IconChevronDown />
                    </Button>
                }
            />
            <DropdownMenuContent className="w-auto min-w-56">
                {adapters.length > 1 && (
                    <PickerSection
                        title="Harness"
                        current={getRuntimeAdapterLabel(selectedAdapter)}
                        value={selectedAdapter}
                        onValueChange={selectAdapter}
                    >
                        {adapters.map((adapter) => (
                            <DropdownMenuRadioItem
                                key={adapter}
                                value={adapter}
                                disabled={!!lockedRuntimeAdapter && adapter !== lockedRuntimeAdapter}
                            >
                                {getRuntimeAdapterLabel(adapter)}
                            </DropdownMenuRadioItem>
                        ))}
                    </PickerSection>
                )}

                <PickerSection
                    title="Model"
                    current={modelLabel}
                    value={selectedModel}
                    onValueChange={(value) => {
                        onModelChange(value)
                        setOpen(false)
                    }}
                >
                    {adapterModels.map((option) => (
                        <DropdownMenuRadioItem key={option.model} value={option.model}>
                            {option.display_name}
                        </DropdownMenuRadioItem>
                    ))}
                </PickerSection>

                {/* A model with no effort control reports no supported efforts — then there's nothing to pick. */}
                {effortOptions.length > 0 && (
                    <PickerSection
                        title="Reasoning"
                        current={getEffortLabel(selectedEffort)}
                        value={selectedEffort}
                        onValueChange={(value) => {
                            onEffortChange(value as ReasoningEffortEnumApi)
                            setOpen(false)
                        }}
                    >
                        {effortOptions.map((option) => (
                            <DropdownMenuRadioItem key={option.value} value={option.value}>
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </PickerSection>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
