import { useQuery } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { Pressable, Text } from 'react-native'
import { getInsightSummary } from '@/api/insights'
import { scopeKey } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { objectMeta, objectWebUrl } from './objectTags'
import { openReplyUrl } from './webLinks'

export function InsightCard({ shortId, title }: { shortId: string; title?: string }): ReactElement {
    const styles = useStyles()
    const scope = useProjectScope()
    const insight = useQuery({
        queryKey: ['insight-summary', ...scopeKey(scope), shortId],
        queryFn: ({ signal }) => getInsightSummary(shortId, signal),
        enabled: !!scope,
        staleTime: 5 * 60_000,
        retry: false,
    })
    const url = scope && objectWebUrl(scope.host, scope.projectId, 'insight', shortId)
    const placeholder = insight.isLoading
        ? 'Loading insight…'
        : insight.isError
          ? 'Could not load insight'
          : insight.data === null
            ? 'Insight unavailable'
            : 'Open insight'
    return (
        <Pressable
            accessibilityRole="link"
            disabled={!url}
            onPress={() => {
                if (url) openReplyUrl(url, 'insight_card', { objectKind: 'insight' })
            }}
            style={styles.card}
        >
            <Text style={styles.meta}>{objectMeta('insight')}</Text>
            <Text style={styles.title} numberOfLines={2}>
                {title || insight.data?.name || placeholder}
            </Text>
            {title && (insight.isLoading || insight.isError || insight.data === null) ? (
                <Text style={styles.description}>{placeholder}</Text>
            ) : null}
            {insight.data?.description ? (
                <Text style={styles.description} numberOfLines={3}>
                    {insight.data.description}
                </Text>
            ) : null}
        </Pressable>
    )
}
const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.surface,
        borderColor: colors.hairline,
        borderWidth: 1,
        borderRadius: radii.card,
        padding: 12,
        gap: 6,
        marginBottom: 10,
    },
    meta: { ...type.meta, color: colors.secondary },
    title: { ...type.bodyStrong, color: colors.ink },
    description: { ...type.bodySmall, color: colors.muted },
}))
