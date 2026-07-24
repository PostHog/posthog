import { LemonTag } from '@posthog/lemon-ui'

/** Renders a boolean config/output value as an Enabled/Disabled tag — the canonical boolean indicator across
 *  Replay vision. Pass onClick to make it a clickable toggle. */
export function BooleanTag({ value, onClick }: { value: boolean; onClick?: () => void }): JSX.Element {
    return (
        <LemonTag
            type={value ? 'success' : 'muted'}
            size="small"
            onClick={onClick ? () => onClick() : undefined}
            className={onClick ? 'self-start cursor-pointer' : 'self-start'}
        >
            {value ? 'Enabled' : 'Disabled'}
        </LemonTag>
    )
}
