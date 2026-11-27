import { LemonBanner } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function MarketingQueryError({
    message,
    queryId,
    onRetry,
    loading = false,
}: {
    message: string
    queryId: string | null | undefined
    onRetry: () => void
    loading?: boolean
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Item tone="destructive" size="sm" className="flex-wrap">
                <ItemContent>
                    <Text size="xs" render={<span />}>
                        {message}
                    </Text>
                    {queryId && (
                        <Text size="xs" variant="muted" render={<div className="break-all" />}>
                            <span>Query ID: </span>
                            <span className="font-mono" translate="no">
                                {queryId}
                            </span>
                        </Text>
                    )}
                </ItemContent>
                <ItemActions>
                    <Button
                        variant="outline"
                        onClick={onRetry}
                        loading={loading}
                        data-attr="marketing-query-error-retry"
                    >
                        Retry
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        <LemonBanner
            type="error"
            action={{ children: 'Retry', onClick: onRetry, loading, 'data-attr': 'marketing-query-error-retry' }}
        >
            <span>{message}</span>
            {queryId && (
                <div className="text-muted text-xs break-all">
                    <span>Query ID: </span>
                    <span className="font-mono" translate="no">
                        {queryId}
                    </span>
                </div>
            )}
        </LemonBanner>
    )
}
