import { useActions, useValues } from 'kea'

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

import { runInteractionLogic } from 'products/posthog_ai/frontend/api/logics'
import {
    COMPOSER_MODELS,
    getEffortLabel,
    getEffortsForModel,
    getModelLabel,
} from 'products/posthog_ai/frontend/utils/composerModels'

/**
 * Model + reasoning-effort pickers for the run composer. The selection is owned by `runInteractionLogic`
 * (`selectedModel` / `selectedEffort`, resolving override → run's stored value → default). On a live run,
 * changing either live-switches the agent via the `set_config_option` command (Claude harness only); on a
 * finished run, the selection seeds the next run a send starts. Always active — there's no live agent to talk
 * to when terminal, but the picks still configure the new run.
 */
export function ComposerModelEffortPickers(): JSX.Element {
    const { selectedModel, selectedEffort } = useValues(runInteractionLogic)
    const { setModel, setEffort } = useActions(runInteractionLogic)

    const effortOptions = getEffortsForModel(selectedModel)

    return (
        <div className="flex items-center gap-1 pl-2">
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm">
                            {getModelLabel(selectedModel)}
                            <IconChevronDown />
                        </Button>
                    }
                />
                <DropdownMenuContent className="w-auto min-w-(--anchor-width)">
                    <DropdownMenuRadioGroup value={selectedModel} onValueChange={setModel}>
                        <DropdownMenuLabel>Model</DropdownMenuLabel>
                        {COMPOSER_MODELS.map((option) => (
                            <DropdownMenuRadioItem key={option.value} value={option.value}>
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>

            <DropdownMenu>
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
                    <DropdownMenuRadioGroup value={selectedEffort} onValueChange={setEffort}>
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
