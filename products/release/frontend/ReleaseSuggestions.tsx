import {
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReleaseRow } from './releaseUtils'

export function ReleaseSuggestions({ row }: { row: ReleaseRow }): JSX.Element | null {
    if (!row.suggestions.length) {
        return null
    }
    return (
        <Card size="sm" data-attr="release-suggestions">
            <CardHeader>
                <CardTitle>Worth considering</CardTitle>
            </CardHeader>
            <CardContent>
                <ItemGroup>
                    {row.suggestions.map((suggestion) => (
                        <Item key={suggestion.key} variant="muted" size="sm" className="flex-wrap">
                            <ItemContent className="basis-full">
                                <ItemTitle>{suggestion.title}</ItemTitle>
                                <ItemDescription>{suggestion.detail}</ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={suggestion.to} />}
                                    data-attr={`release-suggestion-${suggestion.key}`}
                                >
                                    {suggestion.label}
                                </Button>
                            </ItemActions>
                        </Item>
                    ))}
                </ItemGroup>
            </CardContent>
        </Card>
    )
}
