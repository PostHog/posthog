import { Badge, Card } from '@posthog/quill'

import { Evidence, ReleaseBadge, labels, variants } from './infrastructureTypes'

export function PipelineNode({
    id,
    title,
    subtitle,
    state,
    badge,
    progress,
    selected,
    onSelect,
}: {
    id: string
    title: string
    subtitle: string
    state: Evidence
    badge?: ReleaseBadge
    progress?: ReleaseBadge
    selected: string
    onSelect: (id: string) => void
}): JSX.Element {
    return (
        <Card className={`pipeline-node node-${id} ${selected === id ? 'selected' : ''}`}>
            <button
                className="node-button"
                aria-pressed={selected === id}
                onClick={() => onSelect(id)}
                data-attr={`infra-stage-${id}`}
            >
                <strong>{title}</strong>
                <span className="node-subtitle">{subtitle}</span>
                <span className="node-badges">
                    <Badge variant={badge?.variant || variants[state]}>{badge?.label || labels[state]}</Badge>
                    {progress && <Badge variant={progress.variant}>{progress.label}</Badge>}
                </span>
            </button>
        </Card>
    )
}
