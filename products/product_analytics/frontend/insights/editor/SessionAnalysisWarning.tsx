import { LemonBanner, Link } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

const SESSIONS_DOCS_URL = 'https://posthog.com/docs/user-guides/sessions'

export function SessionAnalysisWarning(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Item variant="outline" tone="info" size="sm" className="mb-4">
                <ItemContent>
                    <Text size="xs" className="m-0">
                        When using sessions and session properties, events without session IDs will be excluded from the
                        set of results.{' '}
                        <Button variant="link" size="inline" render={<LinkPrimitive to={SESSIONS_DOCS_URL} />}>
                            Learn more about sessions.
                        </Button>
                    </Text>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="info" className="mb-4">
            When using sessions and session properties, events without session IDs will be excluded from the set of
            results. <Link to={SESSIONS_DOCS_URL}>Learn more about sessions.</Link>
        </LemonBanner>
    )
}
