import { useMemo, useRef, useState } from 'react'

import { IconChevronDown, IconChevronLeft, IconGear, IconRevert } from '@posthog/icons'
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
    getDefaultModelForRuntimeAdapter,
    getEffortLabel,
    getEffortsForModel,
    getHarnessLabel,
    getModelCost,
    getModelLabel,
    getRuntimeAdapterForModel,
    listRuntimeAdapters,
    modelsForRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModels'
import {
    ModelAccessEnumApi,
    ModelChoiceApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { useThreadSkin } from '../../hooks/useThreadSkin'
import { ModelCostChip } from '../ModelCostChip'
import { ModelCostFooter } from '../ModelCostFooter'
import type { ThreadSkin } from '../quill/quillThreadContext'
import { ComposerModelEffortSheet } from './ComposerModelEffortSheet'
import { ComposerReasoningSlider } from './ComposerReasoningSlider'

// Separates model and effort in a slider stop key; never appears in a model id or an effort.
const STOP_SEPARATOR = '|'

const BILLING_LABELS: Record<ModelAccessEnumApi, string> = {
    [ModelAccessEnumApi.PosthogGateway]: 'PostHog credits',
    [ModelAccessEnumApi.OwnSubscription]: 'OpenAI (ChatGPT plan)',
}

export interface ComposerCodexBilling {
    value: ModelAccessEnumApi
    /** The ChatGPT plan can only be picked once the user connected a ChatGPT account. */
    planConnected: boolean
    /** A live run keeps the billing it booted with. */
    locked?: boolean
    onChange: (value: ModelAccessEnumApi) => void
    onConnectPlan: () => void
}

export interface ComposerModelEffortPickersProps {
    /** Models to offer, and the efforts each supports. Callers pass `modelCatalogueLogic`'s live catalogue. */
    models: ModelChoiceApi[]
    selectedModel: string
    defaultModel?: string | null
    isDefaultModelLoading?: boolean
    selectedEffort: ReasoningEffortEnumApi
    onModelChange: (model: string) => void
    onEffortChange: (effort: ReasoningEffortEnumApi) => void
    /**
     * The harness a live run already booted, if any. A running sandbox is one agent binary, and the mid-run config
     * channel only carries model/effort — so the other harnesses can't be reached without starting a new run, and are
     * offered as disabled. `null`/omitted means nothing is running and every harness is selectable.
     */
    lockedRuntimeAdapter?: string | null
    /** The selection shown is the resolved default (user/project preference), not an explicit pick for
     * this run — the lemon model trigger renders a "Default ·" prefix so that's visible at a glance. The quill
     * trigger shows only the model, like PostHog Desktop. */
    isDefaultSelection?: boolean
    /** Clears the explicit pick so the run falls back to the resolved default. Omit on a surface with no
     * configured default and the reset row falls back to the ladder's balanced notch. */
    onResetToDefault?: () => void
    /** Takes the user to where the default itself is configured. Passed as a callback rather than a URL so
     * the picker stays free of the app's routing, and an embedding host can send its own audience
     * somewhere else. Omit and the row is absent. */
    onOpenDefaultSettings?: () => void
    /** Who pays for a run on the Codex harness. Shown only while Codex is selected; omit to hide the row. */
    codexBilling?: ComposerCodexBilling
    phoneSheet?: boolean
    singleHarness?: boolean
}

interface PickerSectionProps {
    title: string
    /** Right-aligned summary on the closed row — the value this section currently holds. */
    current: string
    value: string
    onValueChange: (value: string) => void
    children: React.ReactNode
    /** Rendered under the radio list, for a legend the options need to be read against. */
    footer?: React.ReactNode
}

/** One `label … current ›` row of the cascade, opening a radio list. */
const PICKER_CHROME: Record<
    ThreadSkin,
    { triggerVariant: 'outline' | 'default'; icons: boolean; defaultPrefix: boolean }
> = {
    lemon: { triggerVariant: 'outline', icons: true, defaultPrefix: true },
    quill: { triggerVariant: 'default', icons: false, defaultPrefix: false },
}

function PickerSection({ title, current, value, onValueChange, children, footer }: PickerSectionProps): JSX.Element {
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
                {footer}
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
 * Behind Advanced sits the full Harness → Model → Reasoning cascade; a single reset row closes both views. This mirrors
 * the desktop app's merged model + reasoning control so the two surfaces read the same. Every option comes from the
 * passed catalogue; nothing about a specific model is hardcoded here.
 */
export function ComposerModelEffortPickers({
    models,
    selectedModel,
    defaultModel,
    isDefaultModelLoading = false,
    selectedEffort,
    onModelChange,
    onEffortChange,
    lockedRuntimeAdapter,
    isDefaultSelection = false,
    onResetToDefault,
    onOpenDefaultSettings,
    codexBilling,
    phoneSheet = false,
    singleHarness = false,
}: ComposerModelEffortPickersProps): JSX.Element {
    const chrome = PICKER_CHROME[useThreadSkin()]
    const [open, setOpen] = useState(false)
    const [advanced, setAdvanced] = useState(false)
    // Frozen when the Advanced view is entered rather than derived from the ladder: a model pick that steps off a
    // notch would otherwise make the Back row flash in and out while the menu is open.
    const [showBack, setShowBack] = useState(false)
    const pendingChangeRef = useRef<(() => void) | null>(null)

    // The catalogue only changes when the gateway list reloads, so derive the whole tree in one pass — this
    // component re-renders on every keystroke in the composer above it.
    const { selectedAdapter, modelLabel, effortOptions, adapters, adapterModels, ladder, showsAnyCost } =
        useMemo(() => {
            const adapter = getRuntimeAdapterForModel(models, selectedModel)
            const offered = singleHarness ? models : modelsForRuntimeAdapter(models, adapter)
            return {
                selectedAdapter: adapter,
                modelLabel: getModelLabel(models, selectedModel),
                effortOptions: getEffortsForModel(models, selectedModel),
                adapters: listRuntimeAdapters(models),
                adapterModels: offered,
                ladder: getCapabilityLadder(models, adapter),
                // The legend explains a symbol, so it only belongs where a row carries one.
                showsAnyCost: offered.some((option) => !!getModelCost(option.model)),
            }
        }, [models, selectedModel, singleHarness])

    const selectAdapter = (adapter: string): void => {
        const runtimeAdapter = adapter as RuntimeAdapterEnumApi
        const model = getDefaultModelForRuntimeAdapter(models, runtimeAdapter, defaultModel)
        if (model && model !== selectedModel) {
            onModelChange(model)
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

    const billing = selectedAdapter === RuntimeAdapterEnumApi.Codex ? codexBilling : undefined

    // With neither a configured default to fall back to nor a ladder to land on, there is nothing to reset to.
    const showReset = Boolean(onResetToDefault) || stops.length > 0

    // Deferred until the menu has finished closing: applying mid-animation re-renders the list the user is
    // watching disappear.
    const selectAndClose = (apply: () => void): void => {
        pendingChangeRef.current = apply
        setOpen(false)
    }

    if (phoneSheet) {
        return (
            <ComposerModelEffortSheet
                modelLabel={modelLabel}
                selectedModel={selectedModel}
                selectedEffort={selectedEffort}
                selectedAdapter={selectedAdapter}
                adapters={adapters}
                adapterModels={adapterModels}
                effortOptions={effortOptions}
                showsAnyCost={showsAnyCost}
                harnessDisabled={(adapter) =>
                    isDefaultModelLoading || (!!lockedRuntimeAdapter && adapter !== lockedRuntimeAdapter)
                }
                billing={billing}
                billingLabels={BILLING_LABELS}
                onModelChange={onModelChange}
                onEffortChange={onEffortChange}
                onAdapterChange={selectAdapter}
                resetDisabled={Boolean(onResetToDefault) && isDefaultSelection}
                onReset={
                    showReset
                        ? (onResetToDefault ?? (() => selectStop(stops[Math.floor((stops.length - 1) / 2)])))
                        : undefined
                }
                onOpenDefaultSettings={onOpenDefaultSettings}
            />
        )
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
                    <Button variant={chrome.triggerVariant} size="sm">
                        {isDefaultSelection && chrome.defaultPrefix ? `Default · ${modelLabel}` : modelLabel}
                        {effortOptions.length > 0 && (
                            <span className="text-muted">{getEffortLabel(selectedEffort)}</span>
                        )}
                        {billing?.value === ModelAccessEnumApi.OwnSubscription && (
                            <span className="text-muted">ChatGPT plan</span>
                        )}
                        {chrome.icons && <IconChevronDown />}
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
                        {!singleHarness && adapters.length > 1 && (
                            <PickerSection
                                title="Harness"
                                current={getHarnessLabel(selectedAdapter)}
                                value={selectedAdapter}
                                onValueChange={selectAdapter}
                            >
                                {adapters.map((adapter) => (
                                    <DropdownMenuRadioItem
                                        key={adapter}
                                        value={adapter}
                                        disabled={
                                            isDefaultModelLoading ||
                                            (!!lockedRuntimeAdapter && adapter !== lockedRuntimeAdapter)
                                        }
                                    >
                                        {getHarnessLabel(adapter)}
                                    </DropdownMenuRadioItem>
                                ))}
                            </PickerSection>
                        )}

                        {billing && (
                            <PickerSection
                                title="Billing"
                                current={BILLING_LABELS[billing.value]}
                                value={billing.value}
                                onValueChange={(value) => {
                                    billing.onChange(value as ModelAccessEnumApi)
                                    setOpen(false)
                                }}
                                footer={
                                    billing.planConnected || billing.locked ? undefined : (
                                        <>
                                            <DropdownMenuSeparator />
                                            <DropdownMenuItem
                                                onClick={() => selectAndClose(billing.onConnectPlan)}
                                                data-attr="composer-codex-connect-plan"
                                            >
                                                Connect your ChatGPT account
                                            </DropdownMenuItem>
                                        </>
                                    )
                                }
                            >
                                {[ModelAccessEnumApi.PosthogGateway, ModelAccessEnumApi.OwnSubscription].map(
                                    (value) => (
                                        <DropdownMenuRadioItem
                                            key={value}
                                            value={value}
                                            disabled={
                                                billing.locked ||
                                                (value === ModelAccessEnumApi.OwnSubscription && !billing.planConnected)
                                            }
                                        >
                                            {BILLING_LABELS[value]}
                                        </DropdownMenuRadioItem>
                                    )
                                )}
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
                            footer={showsAnyCost ? <ModelCostFooter /> : undefined}
                        >
                            {adapterModels.map((option) => (
                                <DropdownMenuRadioItem key={option.model} value={option.model}>
                                    <span className="flex w-full items-center justify-between gap-2">
                                        {option.display_name}
                                        <ModelCostChip model={option.model} />
                                    </span>
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

                {(showReset || onOpenDefaultSettings) && <DropdownMenuSeparator />}

                {/* One reset for both meanings of "default": drop the pick so the configured project/user
                    default applies where a surface knows about one, else land on the ladder's balanced
                    notch. Two rows for the two notions read as a duplicate, since only one ever acts. */}
                {showReset && (
                    <DropdownMenuItem
                        disabled={Boolean(onResetToDefault) && isDefaultSelection}
                        onClick={() =>
                            selectAndClose(
                                onResetToDefault ?? (() => selectStop(stops[Math.floor((stops.length - 1) / 2)]))
                            )
                        }
                    >
                        {chrome.icons && <IconRevert />}
                        Reset to default
                    </DropdownMenuItem>
                )}

                {/* Sits under the reset row because that's where the question arises: reverting to a default
                    you disagree with is the moment you want to change it. */}
                {onOpenDefaultSettings && (
                    <DropdownMenuItem onClick={() => selectAndClose(onOpenDefaultSettings)}>
                        {chrome.icons && <IconGear />}
                        Change default
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
