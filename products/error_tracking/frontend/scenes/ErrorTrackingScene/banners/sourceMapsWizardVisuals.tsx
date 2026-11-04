import './sourceMapsWizardVisuals.scss'

import { WizardHog as WizardHogImage } from 'lib/onboarding/wizardHog'
import { cn } from 'lib/utils/css-classes'

export function WizardHog({ castKey = 0, className }: { castKey?: number; className?: string }): JSX.Element {
    return (
        <WizardHogImage
            key={`wizard-hog-${castKey}`}
            className={cn('shrink-0 select-none', castKey > 0 && 'SourceMapsWizard__hogCast', className)}
        />
    )
}
