import { useState } from 'react'

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
import { ModelChoiceApi, ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

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
export function ComposerModelEffortPickers({
    models,
    selectedModel,
    selectedEffort,
    onModelChange,
    onEffortChange,
    lockedRuntimeAdapter,
}: ComposerModelEffortPickersProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const selectedAdapter = getRuntimeAdapterForModel(models, selectedModel)
    const effortOptions = getEffortsForModel(models, selectedModel)
    const adapters = listRuntimeAdapters(models)
    const adapterModels = modelsForRuntimeAdapter(models, selectedAdapter)

    // Switching harness picks that harness's first model; the caller clamps the effort to one it supports.
    const selectAdapter = (adapter: string): void => {
        const first = modelsForRuntimeAdapter(models, adapter)[0]
        if (first && first.model !== selectedModel) {
            onModelChange(first.model)
        }
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <Button variant="outline" size="sm">
                        {getModelLabel(models, selectedModel)}
                        {effortOptions.length > 0 && (
                            <span className="text-muted">{getEffortLabel(selectedEffort)}</span>
                        )}
                        <IconChevronDown />
                    </Button>
                }
            />
            <DropdownMenuContent className="w-auto min-w-56">
                {adapters.length > 1 && (
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                            <span>Harness</span>
                            <span className="flex-1 text-right text-muted">
                                {getRuntimeAdapterLabel(selectedAdapter)}
                            </span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuRadioGroup value={selectedAdapter} onValueChange={selectAdapter}>
                                {adapters.map((adapter) => (
                                    <DropdownMenuRadioItem
                                        key={adapter}
                                        value={adapter}
                                        disabled={!!lockedRuntimeAdapter && adapter !== lockedRuntimeAdapter}
                                    >
                                        {getRuntimeAdapterLabel(adapter)}
                                    </DropdownMenuRadioItem>
                                ))}
                            </DropdownMenuRadioGroup>
                            {lockedRuntimeAdapter && (
                                <p className="px-2 py-1 m-0 text-xs text-muted max-w-56">
                                    This run is already going on {getRuntimeAdapterLabel(lockedRuntimeAdapter)}. Send
                                    once it finishes to start a new run on a different harness.
                                </p>
                            )}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )}

                <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                        <span>Model</span>
                        <span className="flex-1 text-right text-muted">{getModelLabel(models, selectedModel)}</span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        <DropdownMenuRadioGroup
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
                        </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                </DropdownMenuSub>

                {/* A model with no effort control reports no supported efforts — then there's nothing to pick. */}
                {effortOptions.length > 0 && (
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger>
                            <span>Reasoning</span>
                            <span className="flex-1 text-right text-muted">{getEffortLabel(selectedEffort)}</span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuRadioGroup
                                value={selectedEffort}
                                onValueChange={(value: string) => {
                                    onEffortChange(value as ReasoningEffortEnumApi)
                                    setOpen(false)
                                }}
                            >
                                {effortOptions.map((option) => (
                                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                                        {option.label}
                                    </DropdownMenuRadioItem>
                                ))}
                            </DropdownMenuRadioGroup>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
