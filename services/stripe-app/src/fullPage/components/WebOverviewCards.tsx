import { Box, Inline, Spinner } from '@stripe/ui-extension-sdk/ui'

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
}

const WebOverviewCards = ({ items, loading }: Props): JSX.Element => {
    if (loading) {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'large' }}>
                <Spinner />
            </Box>
        )
    }
    const displayItems: WebOverviewItem[] = items && items.length > 0 ? items : DEFAULT_ITEMS

    const allZero = displayItems.every((item: WebOverviewItem) => !item.value || item.value === 0)

    return (
        <Box css={{ stack: 'y' }}>
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
    const delta = deltaText(item)
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
            <Box css={{ stack: 'x', columnGap: 'xsmall', alignY: 'baseline' }}>
                <Inline css={{ font: 'heading' }}>{formatValue(item)}</Inline>
                {delta && <Inline css={{ font: 'caption', color: delta.color }}>{delta.label}</Inline>}
            </Box>
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

function deltaText(item: WebOverviewItem): { label: string; color: 'success' | 'critical' | 'secondary' } | null {
    if (item.changeFromPreviousPct === undefined || item.changeFromPreviousPct === null) {
        return null
    }
    const pct = item.changeFromPreviousPct
    const sign = pct > 0 ? '+' : ''
    const label = `${sign}${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`
    if (pct === 0) {
        return { label, color: 'secondary' }
    }
    const isGood = item.isIncreaseBad ? pct < 0 : pct > 0
    return { label, color: isGood ? 'success' : 'critical' }
}
