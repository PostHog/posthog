import { IconChevronDown } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

export interface QuillBroadcastActionItem {
    label: string
    onClick: () => void
    disabledReason?: string | null
    danger?: boolean
    'data-attr': string
}

export function QuillBroadcastActionsMenu({
    items,
    loading,
}: {
    items: QuillBroadcastActionItem[]
    loading?: boolean
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" loading={loading} data-attr="broadcast-actions" />}>
                Actions
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {items.map((item) => (
                    <DropdownMenuItem
                        key={item['data-attr']}
                        variant={item.danger ? 'destructive' : 'default'}
                        disabledReason={item.disabledReason}
                        onClick={item.onClick}
                        data-attr={item['data-attr']}
                    >
                        {item.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
