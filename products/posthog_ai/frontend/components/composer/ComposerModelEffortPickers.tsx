import { useMemo, useRef, useState } from 'react'

import { IconChevronDown, IconChevronLeft, IconRevert } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import {
    getCapabilityLadder,
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

import { ComposerReasoningSlider } from './ComposerReasoningSlider'

// Separates model and effort in a slider stop key; never appears in a model id or an effort.
const STOP_SEPARATOR = '|'

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

/**
 * Controlled, logic-free model + reasoning-effort picker for a composer footer. The caller owns the selection and the
 * side effects of changing it — the run composer wires it to `runInteractionLogic` (held client-side and applied at
 * send time), the new-task composer wires it to the form that seeds the first run.
 *
 * One chip opens the Faster/Smarter capability slider, whose stops are model + effort pairings from the shared ladder.
 * Behind Advanced sits the full Harness → Model → Reasoning cascade and a reset row. This mirrors the desktop app's
 * merged model + reasoning control so the two surfaces read the same. Every option comes from the passed catalogue;
 * nothing about a specific model is hardcoded here.
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
    const [advanced, setAdvanced] = useState(false)
    // Frozen when the Advanced view is entered rather than derived from the ladder: a model pick that steps off a
    // notch would otherwise make the Back row flash in and out while the menu is open.
    const [showBack, setShowBack] = useState(false)
    const pendingChangeRef = useRef<(() => void) | null>(null)

    // The catalogue only changes when the gateway list reloads, so derive the whole tree in one pass — this
    // component re-renders on every keystroke in the composer above it.
    const { selectedAdapter, modelLabel, effortOptions, adapters, adapterModels, ladder } = useMemo(() => {
        const adapter = getRuntimeAdapterForModel(models, selectedModel)
        return {
            selectedAdapter: adapter,
            modelLabel: getModelLabel(models, selectedModel),
            effortOptions: getEffortsForModel(models, selectedModel),
            adapters: listRuntimeAdapters(models),
            adapterModels: modelsForRuntimeAdapter(models, adapter),
            ladder: getCapabilityLadder(models, adapter),
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

    // A one-rung ladder is no slider, so fall back to the model's plain effort list.
    const useLadder = ladder.length >= 2
    const stops = useLadder
        ? ladder.map((notch) => `${notch.model}${STOP_SEPARATOR}${notch.effort}`)
        : effortOptions.map((option) => option.value as string)
    const currentStop = useLadder ? `${selectedModel}${STOP_SEPARATOR}${selectedEffort}` : selectedEffort

    // A combination assembled in Advanced can sit between rungs. Then the menu opens straight on Advanced until
    // "Reset to default" puts the selection back on a notch.
    const onNotch = useLadder ? stops.includes(currentStop) : effortOptions.length > 0

    const selectStop = (stop: string): void => {
        if (!stop.includes(STOP_SEPARATOR)) {
            onEffortChange(stop as ReasoningEffortEnumApi)
            return
        }
        const [model, effort] = stop.split(STOP_SEPARATOR)
        // Model first: the caller clamps the effort to the new model on the way through, and this pairing is
        // already known to be one it supports.
        if (model !== selectedModel) {
            onModelChange(model)
        }
        if (effort !== selectedEffort) {
            onEffortChange(effort as ReasoningEffortEnumApi)
        }
    }

    // Deferred until the menu has finished closing: applying mid-animation re-renders the list the user is
    // watching disappear.
    const selectAndClose = (apply: () => void): void => {
        pendingChangeRef.current = apply
        setOpen(false)
    }

    return (
        <DropdownMenu
            open={open}
            onOpenChange={(nextOpen) => {
                // Only on the closed-to-open transition: submenu opens re-fire this with true and must not yank
                // the view back.
                if (nextOpen && !open) {
                    setAdvanced(!onNotch)
                    setShowBack(false)
                }
                setOpen(nextOpen)
            }}
            onOpenChangeComplete={(isOpen) => {
                if (!isOpen) {
                    setAdvanced(false)
                    setShowBack(false)
                    pendingChangeRef.current?.()
                    pendingChangeRef.current = null
                }
            }}
        >
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
                {advanced ? (
                    <>
                        {showBack && (
                            <button
                                type="button"
                                className="flex w-full items-center gap-1 px-2 py-1.5 text-xs text-muted hover:text-default"
                                onClick={() => setAdvanced(false)}
                            >
                                <IconChevronLeft className="text-xs" />
                                Back
                            </button>
                        )}
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

                        {stops.length > 0 && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                    onClick={() =>
                                        // The middle notch is the balanced default for the whole ladder.
                                        selectAndClose(() => selectStop(stops[Math.floor((stops.length - 1) / 2)]))
                                    }
                                >
                                    <IconRevert />
                                    Reset to default
                                </DropdownMenuItem>
                            </>
                        )}
                    </>
                ) : (
                    <ComposerReasoningSlider
                        stops={stops}
                        currentStop={currentStop}
                        onSelect={selectStop}
                        onAdvanced={() => {
                            setShowBack(true)
                            setAdvanced(true)
                        }}
                    />
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
