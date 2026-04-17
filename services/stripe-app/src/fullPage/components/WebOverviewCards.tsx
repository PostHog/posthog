import { Badge, Box, Img, Inline, Link, Spinner } from '@stripe/ui-extension-sdk/ui'

import { POSTHOG_ICON_SRC } from '../../constants'
import type { WebOverviewItem } from '../../posthog/types'
import PromoBanner, { PromoBannerText } from './PromoBanner'

const DEFAULT_ITEMS: WebOverviewItem[] = [
    { key: 'visitors', kind: 'unit', value: 0 },
    { key: 'views', kind: 'unit', value: 0 },
    { key: 'sessions', kind: 'unit', value: 0 },
    { key: 'session duration', kind: 'duration_s', value: 0 },
    { key: 'bounce rate', kind: 'percentage', value: 0 },
]

interface Props {
    items: WebOverviewItem[] | null
    loading: boolean
    posthogUrl?: string
}

const WebOverviewCards = ({ items, loading, posthogUrl }: Props): JSX.Element => {
    const header = (
        <Box css={{ stack: 'x', distribute: 'space-between', alignY: 'center', paddingBottom: 'small' }}>
            <Box css={{ stack: 'y', rowGap: 'xxsmall' }}>
                <Inline css={{ font: 'heading' }}>Web analytics</Inline>
                <Inline css={{ font: 'caption', color: 'secondary' }}>Last 30 days</Inline>
            </Box>
            {posthogUrl && (
                <Link href={posthogUrl} target="_blank" type="secondary">
                    <Box css={{ stack: 'x', columnGap: 'xsmall', alignY: 'center' }}>
                        <Img src={POSTHOG_ICON_SRC} alt="PostHog" width="16" height="16" />
                        <Inline>See more in PostHog</Inline>
                    </Box>
                </Link>
            )}
        </Box>
    )

    if (loading) {
        return (
            <Box css={{ stack: 'y' }}>
                {header}
                <Box css={{ stack: 'x', alignX: 'center', padding: 'large' }}>
                    <Spinner />
                </Box>
            </Box>
        )
    }
    const displayItems: WebOverviewItem[] = items && items.length > 0 ? items : DEFAULT_ITEMS

    const allZero = displayItems.every((item: WebOverviewItem) => !item.value || item.value === 0)

    return (
        <Box css={{ stack: 'y' }}>
            {header}
            <Box css={{ stack: 'x', gap: 'medium', wrap: 'wrap' }}>
                {displayItems.map((item: WebOverviewItem) => (
                    <Box key={item.key} css={{ width: '1/5', minWidth: 36 }}>
                        <Card item={item} />
                    </Box>
                ))}
            </Box>
            {allZero && (
                <Box css={{ marginTop: 'small' }}>
                    <PromoBanner>
                        <PromoBannerText>
                            No traffic detected in the last 30 days — add PostHog to your app to start tracking:
                        </PromoBannerText>
                        <Inline css={{ font: 'body', fontFamily: 'monospace', color: 'info' }}>
                            npx @posthog/wizard
                        </Inline>
                    </PromoBanner>
                </Box>
            )}
        </Box>
    )
}

export default WebOverviewCards

const Card = ({ item }: { item: WebOverviewItem }): JSX.Element => {
    const chip = deltaChip(item)
    return (
        <Box
            css={{
                stack: 'y',
                rowGap: 'xsmall',
                padding: 'medium',
                borderRadius: 'medium',
                borderWidth: 1,
                borderColor: 'neutral',
                backgroundColor: 'surface',
                width: 'fill',
                minWidth: 48,
            }}
        >
            <Inline css={{ font: 'caption', color: 'secondary', textTransform: 'capitalize' }}>
                {titleCase(item.key)}
            </Inline>
            <Inline css={{ font: 'heading' }}>{formatValue(item)}</Inline>
            {chip && (
                <Box css={{ stack: 'x' }}>
                    <Badge type={chip.type}>{chip.label}</Badge>
                </Box>
            )}
        </Box>
    )
}

function titleCase(key: string): string {
    return key.replace(/\b\w/g, (m) => m.toUpperCase())
}

function formatValue(item: WebOverviewItem): string {
    if (item.value === undefined || item.value === null) {
        return '—'
    }
    if (item.kind === 'percentage') {
        return `${(item.value * 100).toFixed(1)}%`
    }
    if (item.kind === 'duration_s') {
        const s = Math.round(item.value)
        if (s < 60) {
            return `${s}s`
        }
        const m = Math.floor(s / 60)
        const rs = s % 60
        return `${m}m ${rs}s`
    }
    if (item.kind === 'currency') {
        return `$${item.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    }
    if (item.value >= 1_000_000) {
        return `${(item.value / 1_000_000).toFixed(1)}M`
    }
    if (item.value >= 1_000) {
        return `${(item.value / 1_000).toFixed(1)}K`
    }
    return item.value.toLocaleString()
}

function deltaChip(item: WebOverviewItem): { label: string; type: 'positive' | 'negative' | 'neutral' } | null {
    if (item.changeFromPreviousPct === undefined || item.changeFromPreviousPct === null) {
        return null
    }
    const pct = item.changeFromPreviousPct
    const sign = pct > 0 ? '+' : ''
    const label = `${sign}${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`
    if (pct === 0) {
        return { label, type: 'neutral' }
    }
    const isGood = item.isIncreaseBad ? pct < 0 : pct > 0
    return { label, type: isGood ? 'positive' : 'negative' }
}
