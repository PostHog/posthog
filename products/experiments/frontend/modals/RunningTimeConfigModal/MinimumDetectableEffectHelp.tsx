export interface MinimumDetectableEffectHelpProps {
    // The color too, so that the text matches the other hints where it sits.
    className: string
}

export function MinimumDetectableEffectHelp({ className }: MinimumDetectableEffectHelpProps): JSX.Element {
    return (
        <div className={`text-xs ${className}`}>
            The minimum detectable effect is the smallest change you want to detect, relative to the control. Smaller
            changes are harder to tell apart from random noise, so they need more exposures. It affects only the running
            time, not how the metrics are calculated.
        </div>
    )
}
