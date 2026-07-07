import { useState } from 'react'

import { IconBrain, IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill-primitives'

import {
    COMPOSER_MODELS,
    getEffortLabel,
    getEffortsForModel,
    getModelLabel,
} from 'products/posthog_ai/frontend/utils/composerModels'
import { ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export interface ComposerModelEffortPickersProps {
    selectedModel: string
    selectedEffort: ReasoningEffortEnumApi
    onModelChange: (model: string) => void
    onEffortChange: (effort: ReasoningEffortEnumApi) => void
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
}: ComposerModelEffortPickersProps): JSX.Element {
    const effortOptions = getEffortsForModel(selectedModel)
    const [modelOpen, setModelOpen] = useState(false)
    const [effortOpen, setEffortOpen] = useState(false)

    return (
        <div className="flex items-center gap-1 pl-2">
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
                        <DropdownMenuLabel>Model</DropdownMenuLabel>
                        {COMPOSER_MODELS.map((option) => (
                            <DropdownMenuRadioItem key={option.value} value={option.value}>
                                {option.label}
                            </DropdownMenuRadioItem>
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
