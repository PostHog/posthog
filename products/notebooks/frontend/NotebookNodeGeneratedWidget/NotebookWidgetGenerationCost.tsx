import { LemonLabel } from '@posthog/lemon-ui'

export function NotebookWidgetGenerationCost({ cost }: { cost: string | null | undefined }): JSX.Element {
    return (
        <div className="text-sm" data-attr="widget-generation-cost">
            <LemonLabel>Estimated generation cost</LemonLabel>
            {cost != null ? (
                <>
                    <div className="mt-1 font-mono tabular-nums" translate="no">
                        {Number(cost) > 0 && Number(cost) < 0.01 ? '< $0.01' : `$${Number(cost).toFixed(2)}`}
                    </div>
                    <div className="mt-1 text-xs text-muted">
                        Includes this version's generation, security review, retries, and 20% markup. Final AI credits
                        may differ due to billing rounding.
                    </div>
                </>
            ) : (
                <div className="mt-1 text-secondary">Cost unavailable for this version.</div>
            )}
        </div>
    )
}
