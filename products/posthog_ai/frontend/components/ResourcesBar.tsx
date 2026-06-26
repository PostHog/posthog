import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { runStreamLogic } from '../logics/runStreamLogic'
import { resolveProductMeta } from '../messages/posthogProducts'

/**
 * Persistent "PostHog resources used" bar for sandbox conversations. Reads the session-cumulative
 * `resourcesUsed` list (unioned by id across the whole conversation) and renders one chip per
 * product the agent grounded an answer in. Hidden when empty. Each chip is a product icon plus a
 * Sentence-cased label; unknown ids degrade to the wire label and a generic icon.
 */
export function ResourcesBar(): JSX.Element | null {
    const { resourcesUsed } = useValues(runStreamLogic)

    if (resourcesUsed.length === 0) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5" data-attr="max-sandbox-resources-bar">
            <span className="text-xs text-muted mr-0.5">PostHog resources used:</span>
            {resourcesUsed.map((product) => {
                const { label, Icon } = resolveProductMeta(product.id, product.label)
                return (
                    <Tooltip key={product.id} title={label}>
                        <span className="inline-flex items-center gap-1 rounded border bg-surface-primary px-1.5 py-0.5 text-xs">
                            <Icon className="size-3.5 shrink-0" />
                            <span>{label}</span>
                        </span>
                    </Tooltip>
                )
            })}
        </div>
    )
}
