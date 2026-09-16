import { LemonTag } from '@posthog/lemon-ui'

export const CUPED_ADJUSTED_EXPLANATION =
    'CUPED uses pre-experiment data to reduce variance, so the delta compares adjusted means. It will not match the difference between the values shown.'

/** Marks a delta that CUPED adjusted, so nobody reads it as the difference of the values beside it. */
export function CupedAdjustedTag(): JSX.Element {
    return (
        <LemonTag type="muted" size="small">
            CUPED
        </LemonTag>
    )
}
