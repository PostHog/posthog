import { Tooltip } from '@posthog/lemon-ui'

export function TileAttentionMarker(): JSX.Element {
    return (
        <Tooltip title="This step needs attention. Open it to see what is missing.">
            <span className="absolute -left-1 -top-1 size-2.5 rounded-full border-2 border-primary bg-warning" />
        </Tooltip>
    )
}
