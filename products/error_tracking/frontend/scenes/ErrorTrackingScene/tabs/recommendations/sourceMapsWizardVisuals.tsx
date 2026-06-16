import './sourceMapsWizardVisuals.scss'

import { cn } from 'lib/utils/css-classes'

// Same wizard hedgehog used by the onboarding install step.
export const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

export function WizardHog({ castKey = 0, className }: { castKey?: number; className?: string }): JSX.Element {
    return (
        <img
            key={`wizard-hog-${castKey}`}
            src={WIZARD_HOG_URL}
            alt="PostHog wizard hedgehog"
            className={cn('shrink-0 select-none', castKey > 0 && 'SourceMapsWizard__hogCast', className)}
        />
    )
}
