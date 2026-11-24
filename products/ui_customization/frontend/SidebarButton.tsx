import { AutocompleteItem, Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { AnalyticsFragmentButtonApi } from './generated/api.schemas'

export function SidebarButton({
    value,
    target,
    resolved,
    dataAttr,
}: {
    value: string
    target: AnalyticsFragmentButtonApi
    resolved: { to: string; label: string; icon?: JSX.Element | null } | null
    dataAttr: string
}): JSX.Element | null {
    if (!resolved) {
        return null
    }
    return (
        <AutocompleteItem
            value={value}
            render={
                <Button
                    size="sm"
                    variant={target.variant ?? 'outline'}
                    nativeButton={false}
                    render={<LinkPrimitive to={resolved.to} />}
                    className="my-1 w-full justify-start data-highlighted:ring-2"
                />
            }
            data-attr={dataAttr}
        >
            {resolved.icon}
            <span className="truncate">{resolved.label}</span>
        </AutocompleteItem>
    )
}
