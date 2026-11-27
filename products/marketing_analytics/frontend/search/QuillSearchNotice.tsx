import { Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillSearchNotice({
    tone = 'info',
    action,
    children,
}: {
    tone?: 'info' | 'destructive'
    action?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <Item tone={tone} size="sm" className="flex-wrap">
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
            </ItemContent>
            {action ? <ItemActions>{action}</ItemActions> : null}
        </Item>
    )
}
