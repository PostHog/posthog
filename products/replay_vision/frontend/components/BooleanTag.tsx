import { LemonTag } from '@posthog/lemon-ui'

/** Renders a boolean config/output value as an Enabled/Disabled tag — the canonical boolean indicator across Replay vision. */
export function BooleanTag({ value }: { value: boolean }): JSX.Element {
    return (
        <LemonTag type={value ? 'success' : 'muted'} size="small" className="self-start">
            {value ? 'Enabled' : 'Disabled'}
        </LemonTag>
    )
}
