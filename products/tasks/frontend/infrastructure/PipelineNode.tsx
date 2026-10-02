import { Badge, Card } from '@posthog/quill'

import { Evidence, labels, variants } from './infrastructureTypes'

export function PipelineNode({
    id,
    title,
    subtitle,
    state,
    selected,
    onSelect,
}: {
    id: string
    title: string
    subtitle: string
    state: Evidence
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
                <Badge variant={variants[state]}>{labels[state]}</Badge>
            </button>
        </Card>
    )
}
