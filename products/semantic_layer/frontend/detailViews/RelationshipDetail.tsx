import { LemonTag } from '@posthog/lemon-ui'

import { RelationshipProposal } from '../proposalTypes'

const REL_LABEL: Record<RelationshipProposal['relationshipType'], string> = {
    one_to_one: '1 ↔ 1',
    one_to_many: '1 ↔ N',
    many_to_many: 'N ↔ N',
}

export function RelationshipDetail({ proposal }: { proposal: RelationshipProposal }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <section className="border rounded p-4 bg-surface-primary">
                <div className="flex items-center justify-center gap-4">
                    <EntityChip entity={proposal.leftSide.entity} field={proposal.leftSide.field} />
                    <div className="flex flex-col items-center">
                        <span className="text-xs text-muted-alt">join</span>
                        <span className="font-mono text-sm">{REL_LABEL[proposal.relationshipType]}</span>
                    </div>
                    <EntityChip entity={proposal.rightSide.entity} field={proposal.rightSide.field} />
                </div>
            </section>

            <section>
                <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Sample matches</h4>
                <div className="flex flex-col gap-1 text-xs font-mono">
                    {proposal.sampleMatches.map((m, i) => (
                        <div key={i} className="grid grid-cols-2 gap-2 p-2 border rounded bg-surface-primary">
                            <span className="truncate">{m.left}</span>
                            <span className="truncate text-muted-alt">→ {m.right}</span>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    )
}

function EntityChip({ entity, field }: { entity: string; field: string }): JSX.Element {
    return (
        <div className="border rounded p-3 min-w-32 text-center">
            <LemonTag type="primary" size="small">
                {entity}
            </LemonTag>
            <div className="font-mono text-xs mt-1.5">{field}</div>
        </div>
    )
}
