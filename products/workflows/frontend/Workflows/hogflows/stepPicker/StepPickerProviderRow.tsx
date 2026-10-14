import { useActions } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { stepPickerLogic } from './stepPickerLogic'
import { StepProvider, stepCountLabel } from './stepPickerPresentation'
import { StepPickerProviderIcon } from './StepPickerProviderIcon'

export function StepPickerProviderRow({ provider }: { provider: StepProvider }): JSX.Element {
    const { openProvider } = useActions(stepPickerLogic)

    return (
        <li className="min-w-0">
            <LemonButton
                fullWidth
                icon={<StepPickerProviderIcon provider={provider} size="md" />}
                sideIcon={<IconChevronRight />}
                onClick={() => openProvider(provider.id)}
                data-attr="workflow-step-picker-provider"
            >
                <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate" data-attr="workflow-step-picker-provider-label">
                        {provider.label}
                    </span>
                    <span className="text-xs font-normal text-secondary">
                        {stepCountLabel(provider.entries.length)}
                    </span>
                </span>
            </LemonButton>
        </li>
    )
}
