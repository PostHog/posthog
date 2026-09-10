import { Tooltip } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill-primitives'

// Shared thresholds for reading a routing-entropy-scaled score: below 0.3 one
// tool dominates, above 0.6 calls spread across many tools. Used for both a
// cluster's entropy and a tool's contested score, so the two read the same.
export function EntropyBadge({ entropy }: { entropy: number }): JSX.Element {
    if (entropy < 0.3) {
        return (
            <Tooltip title={`Routing entropy ${entropy.toFixed(2)} — one tool dominates this cluster's calls.`}>
                <span>
                    <Badge variant="success">Concentrated · {entropy.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    if (entropy < 0.6) {
        return (
            <Tooltip title={`Routing entropy ${entropy.toFixed(2)} — calls split between a few tools.`}>
                <span>
                    <Badge variant="warning">Mixed · {entropy.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip
            title={`Routing entropy ${entropy.toFixed(2)} — calls spread across many tools. Either a real multi-step workflow or the agent is improvising; the aggregate alone can't tell.`}
        >
            <span>
                <Badge variant="destructive">Spread · {entropy.toFixed(2)}</Badge>
            </span>
        </Tooltip>
    )
}

// A tool's contested score is entropy-scaled, so it reuses the same bands with
// tool-appropriate wording.
export function ContestedBadge({ score }: { score: number | null }): JSX.Element {
    if (score === null) {
        return <span className="text-muted">—</span>
    }
    if (score < 0.3) {
        return (
            <Tooltip title={`Contested score ${score.toFixed(2)}. This tool is the clear choice for its intents.`}>
                <span>
                    <Badge variant="success">Clear · {score.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    if (score < 0.6) {
        return (
            <Tooltip
                title={`Contested score ${score.toFixed(2)}. Some of this tool's intents also route to other tools.`}
            >
                <span>
                    <Badge variant="warning">Shared · {score.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip
            title={`Contested score ${score.toFixed(2)}. The intents this tool serves are regularly split across several tools.`}
        >
            <span>
                <Badge variant="destructive">Contested · {score.toFixed(2)}</Badge>
            </span>
        </Tooltip>
    )
}
