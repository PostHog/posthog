import { IconLogomark } from '@posthog/icons'

import { StepProvider } from './stepPickerPresentation'
import { StepPickerStepIcon } from './StepPickerStepIcon'

export function StepPickerProviderIcon({ provider, size }: { provider: StepProvider; size: 'md' | 'lg' }): JSX.Element {
    if (provider.product) {
        return (
            <span
                className={`flex shrink-0 items-center justify-center text-primary ${size === 'lg' ? 'size-10 text-3xl' : 'size-7 text-xl'}`}
            >
                <IconLogomark />
            </span>
        )
    }
    return <StepPickerStepIcon entry={provider.entries[0]} size={size} />
}
