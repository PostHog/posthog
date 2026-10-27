import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { AiBrandLogo, resolveAiBrand } from 'products/web_analytics/frontend/searchAndAi/AiBrandLogo'

export function CrawlerLogoStack({ names, count }: { names: string[]; count: number }): JSX.Element {
    const hidden = Math.max(count - names.length, 0)
    const brandNames = [...new Map(names.map((name) => [resolveAiBrand(name)?.domain ?? name, name])).values()]
    return (
        <Tooltip title={names.length > 0 ? `Read by ${names.join(', ')}${hidden ? ` and ${hidden} more` : ''}` : null}>
            <span className="inline-flex items-center gap-1.5" data-attr="page-directory-crawler-logos">
                {brandNames.length > 0 ? (
                    <span className="flex items-center">
                        {brandNames.map((name) => (
                            <span
                                key={name}
                                className="-ml-0.5 first:ml-0 rounded-sm outline-2 outline-solid outline-[var(--color-bg-surface-primary)]"
                            >
                                <AiBrandLogo name={name} size="xs" />
                            </span>
                        ))}
                    </span>
                ) : null}
                <span className="text-xs text-secondary whitespace-nowrap">{pluralize(count, 'crawler')}</span>
            </span>
        </Tooltip>
    )
}
