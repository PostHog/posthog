import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

export function QuillGatewayServersLoadError({
    onRetry,
    serverDetail = false,
}: {
    onRetry: () => void
    serverDetail?: boolean
}): JSX.Element {
    return (
        <Item tone="destructive" size="sm">
            <ItemContent>
                <ItemDescription>
                    {serverDetail
                        ? "Couldn't load this MCP server. Try again."
                        : "Couldn't load MCP servers. Try again."}
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline" onClick={onRetry}>
                    Try again
                </Button>
            </ItemActions>
        </Item>
    )
}
