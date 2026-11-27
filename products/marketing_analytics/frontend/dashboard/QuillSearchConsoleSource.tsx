import type { ReactNode } from 'react'

import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass'
import {
    Button,
    Card,
    CardContent,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Spinner,
    Text,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)

export function QuillSearchConsoleSource({
    view,
    headerAction,
    sources,
    restrictedReason,
    retryLoading,
    onRetry,
}: {
    view: 'error' | 'checking' | 'connect'
    headerAction?: ReactNode
    sources: { type: string; name: string; connectUrl: string }[]
    restrictedReason: string | null
    retryLoading: boolean
    onRetry: () => void
}): JSX.Element {
    return (
        <section className="mt-8 mb-6 flex w-full flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
                <Heading render={<h2 className="m-0" />}>Search performance</Heading>
                {view !== 'connect' && headerAction}
            </div>
            {view === 'error' ? (
                <Item tone="destructive" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemDescription>
                            Could not check your search connections. Try again to load your sources.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={onRetry} loading={retryLoading}>
                            Try again
                        </Button>
                    </ItemActions>
                </Item>
            ) : view === 'checking' ? (
                <Card>
                    <CardContent>
                        <div className="flex items-start gap-4" role="status">
                            <Spinner className="mt-1 shrink-0" />
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                                <Heading size="base" render={<h3 className="m-0" />}>
                                    Checking your search connections
                                </Heading>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Looking for connected search sources.
                                </Text>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            ) : (
                <Card data-attr="marketing-search-console-extra">
                    <CardContent className="flex flex-col gap-4">
                        <div className="flex items-start gap-4">
                            <div className="flex min-w-0 flex-1 flex-col gap-1">
                                <Heading size="base" render={<h3 className="m-0" />}>
                                    Connect your search sources
                                </Heading>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Google Search Console shows organic queries, landing pages and average positions.
                                    Connect Google Ads or Bing Ads to compare paid keywords with organic queries and use
                                    spend and conversion data to guide your search ad decisions.
                                </Text>
                            </div>
                            <HedgehogMagnifyingGlass className="w-20 shrink-0" />
                            {headerAction}
                        </div>
                        <div className="flex flex-col divide-y divide-border">
                            {sources.map((source) => (
                                <div
                                    key={source.type}
                                    className="flex flex-wrap items-center justify-between gap-3 py-2"
                                >
                                    <div className="flex min-w-0 items-center gap-3">
                                        <SourceIcon type={source.type} size="small" disableTooltip />
                                        <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                            {source.name}
                                        </Text>
                                    </div>
                                    <Button
                                        variant="outline"
                                        disabledReason={restrictedReason}
                                        nativeButton={false}
                                        render={<LinkPrimitive to={source.connectUrl} />}
                                    >
                                        Connect
                                    </Button>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>
            )}
        </section>
    )
}
