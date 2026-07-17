import './sourceMapsWizardVisuals.scss'

import { cn } from 'lib/utils/css-classes'
import { WIZARD_HOG_URL } from 'scenes/onboarding/shared/wizardHog'

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
