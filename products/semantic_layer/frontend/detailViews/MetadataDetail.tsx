import { LemonBanner } from '@posthog/lemon-ui'

import { MetadataProposal } from '../proposalTypes'

export function MetadataDetail({ proposal }: { proposal: MetadataProposal }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <LemonBanner type="info" className="text-sm">
                Metadata changes are low-stakes. You can <strong>Approve all</strong> below, or open individual entries
                to edit.
            </LemonBanner>
            <section>
                <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Suggested changes</h4>
                <div className="flex flex-col gap-2">
                    {proposal.changes.map((c) => (
                        <details key={c.field} className="border rounded bg-surface-primary">
                            <summary className="px-3 py-2 cursor-pointer text-sm font-mono">{c.field}</summary>
                            <div className="grid grid-cols-2 text-xs font-mono border-t">
                                <div className="p-3 bg-danger-highlight border-r whitespace-pre-wrap">
                                    <div className="text-[10px] uppercase text-danger mb-1">before</div>
                                    {c.before}
                                </div>
                                <div className="p-3 bg-success-highlight whitespace-pre-wrap">
                                    <div className="text-[10px] uppercase text-success mb-1">after</div>
                                    {c.after}
                                </div>
                            </div>
                        </details>
                    ))}
                </div>
            </section>
        </div>
    )
}
