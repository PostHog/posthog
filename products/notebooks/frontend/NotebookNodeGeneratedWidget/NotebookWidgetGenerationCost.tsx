import { IconInfo } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

export function NotebookWidgetGenerationCost({ cost }: { cost: string | null | undefined }): JSX.Element | null {
    if (cost == null) {
        return null
    }

    return (
        <div className="flex shrink-0 items-center gap-0.5 text-xs text-muted" data-attr="widget-generation-cost">
            <span className="font-mono tabular-nums" translate="no">
                {Number(cost) > 0 && Number(cost) < 0.01 ? '< $0.01' : `$${Number(cost).toFixed(2)}`}
            </span>
            <Tooltip
                openOnClick
                title={
                    <>
                        <div className="mb-1 font-semibold">Estimated generation cost</div>
                        Includes this version's generation, security review, retries, and 20% markup. Final PostHog AI
                        credits may differ due to billing rounding.
                    </>
                }
            >
                <LemonButton
                    size="xsmall"
                    icon={<IconInfo />}
                    aria-label="About this generation's cost"
                    data-attr="widget-generation-cost-info"
                    className="text-muted"
                />
            </Tooltip>
        </div>
    )
}
