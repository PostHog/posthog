import { Badge, Box, Inline } from '@stripe/ui-extension-sdk/ui'

type BadgeType = 'neutral' | 'urgent' | 'warning' | 'negative' | 'positive' | 'info'

export interface MetricRowProps {
    label: string
    value: string
    badgeLabel?: string
    badgeType?: BadgeType
    deltaPct?: number
}

const MetricRow = ({ label, value, badgeLabel, badgeType, deltaPct }: MetricRowProps): JSX.Element => {
    const delta = deltaPct !== undefined ? formatDelta(deltaPct) : undefined
    const deltaType: BadgeType = deltaPct === undefined ? 'neutral' : deltaPct >= 0 ? 'positive' : 'negative'

    return (
        <Box css={{ stack: 'x', distribute: 'space-between', alignY: 'center', paddingY: 'xsmall' }}>
            <Box css={{ stack: 'y', rowGap: 'xxsmall' }}>
                <Inline css={{ font: 'body', fontFamily: 'monospace' }}>{label}</Inline>
                <Inline css={{ font: 'caption', color: 'secondary' }}>{value}</Inline>
            </Box>
            <Box css={{ stack: 'x', columnGap: 'xsmall', alignY: 'center' }}>
                {badgeLabel && <Badge type={badgeType ?? 'neutral'}>{badgeLabel}</Badge>}
                {delta && <Badge type={deltaType}>{delta}</Badge>}
            </Box>
        </Box>
    )
}

export default MetricRow

function formatDelta(pct: number): string {
    const sign = pct >= 0 ? '+' : ''
    const fixed = pct.toFixed(Math.abs(pct) < 10 && pct % 1 !== 0 ? 1 : 0)
    return `${sign}${fixed}%`
}
