import { Fragment, useMemo, useState } from 'react'

import { IconBrain, IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import {
    COMPOSER_MODELS,
    type ComposerModelOption,
    getEffortLabel,
    getEffortsForModel,
    getModelLabel,
    groupModelsByRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModels'
import { ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export interface ComposerModelEffortPickersProps {
    selectedModel: string
    selectedEffort: ReasoningEffortEnumApi
    onModelChange: (model: string) => void
    onEffortChange: (effort: ReasoningEffortEnumApi) => void
    /** Narrows the models on offer — a live run can only switch within the runtime it was launched on. */
    models?: ComposerModelOption[]
}

/**
 * Controlled, logic-free model + reasoning-effort pickers for a composer footer. The caller owns the selection
 * and the side effects of changing it — the run composer wires it to `runInteractionLogic` (held client-side and
 * applied at send time), the new-task composer wires it to the form that seeds the first run. This component only
 * renders the dropdowns and reports changes up.
 */
export function ComposerModelEffortPickers({
    selectedModel,
    selectedEffort,
    onModelChange,
    onEffortChange,
    models = COMPOSER_MODELS,
}: ComposerModelEffortPickersProps): JSX.Element {
    const effortOptions = getEffortsForModel(selectedModel)
    const modelGroups = useMemo(() => groupModelsByRuntimeAdapter(models), [models])
    const [modelOpen, setModelOpen] = useState(false)
    const [effortOpen, setEffortOpen] = useState(false)

    return (
        <div className="flex items-center gap-1">
            <DropdownMenu open={modelOpen} onOpenChange={setModelOpen}>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm">
                            {getModelLabel(selectedModel)}
                            <IconChevronDown />
                        </Button>
                    }
                />
                <DropdownMenuContent className="w-auto min-w-(--anchor-width)">
                    <DropdownMenuRadioGroup
                        value={selectedModel}
                        onValueChange={(value) => {
                            onModelChange(value)
                            setModelOpen(false)
                        }}
                    >
                        {/* Sectioned by harness, so it's clear which agent a model actually runs in. */}
                        {modelGroups.map((group, index) => (
                            <Fragment key={group.adapter}>
                                {index > 0 && <DropdownMenuSeparator />}
                                <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
                                {group.models.map((option) => (
                                    <DropdownMenuRadioItem key={option.value} value={option.value}>
                                        {option.label}
                                    </DropdownMenuRadioItem>
                                ))}
                            </Fragment>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu open={effortOpen} onOpenChange={setEffortOpen}>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm">
                            <IconBrain />
                            {getEffortLabel(selectedEffort)}
                            <IconChevronDown />
                        </Button>
                    }
                />
                <DropdownMenuContent className="w-auto min-w-(--anchor-width)">
                    <DropdownMenuRadioGroup
                        value={selectedEffort}
                        onValueChange={(value: string) => {
                            onEffortChange(value as ReasoningEffortEnumApi)
                            setEffortOpen(false)
                        }}
                    >
                        <DropdownMenuLabel>Effort</DropdownMenuLabel>
                        {effortOptions.map((option) => (
                            <DropdownMenuRadioItem key={option.value} value={option.value}>
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
