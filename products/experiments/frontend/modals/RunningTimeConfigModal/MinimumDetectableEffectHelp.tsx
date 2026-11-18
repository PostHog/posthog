import { MINIMUM_DETECTABLE_EFFECT_HELP } from './runningTimeConfigModel'

export interface MinimumDetectableEffectHelpProps {
    // The color too, so that the text matches the other hints where it sits.
    className: string
}

export function MinimumDetectableEffectHelp({ className }: MinimumDetectableEffectHelpProps): JSX.Element {
    return <div className={`text-xs ${className}`}>{MINIMUM_DETECTABLE_EFFECT_HELP}</div>
}
