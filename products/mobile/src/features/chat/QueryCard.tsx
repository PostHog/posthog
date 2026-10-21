import { type ReactElement, useState } from 'react'
import { Pressable, Text, View } from 'react-native'
import { useProjectScope } from '@/auth/useProjectScope'
import { createStyles } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { objectMeta, objectWebUrl } from './objectTags'
import { openReplyUrl } from './webLinks'

export function QueryCard({ query, title }: { query: string; title?: string }): ReactElement {
    const styles = useStyles()
    const scope = useProjectScope()
    const url = scope && objectWebUrl(scope.host, scope.projectId, 'hogql', query)
    const [expanded, setExpanded] = useState(false)
    return (
        <View style={styles.card}>
            <Pressable
                accessibilityRole="link"
                disabled={!url}
                onPress={() => {
                    if (url) openReplyUrl(url, 'query_card', { objectKind: 'hogql' })
                }}
            >
                <Text style={styles.meta}>{objectMeta('hogql')}</Text>
                <Text style={styles.title} numberOfLines={2}>
                    {title || 'SQL query'}
                </Text>
                <View style={styles.queryBox}>
                    <Text style={styles.query} numberOfLines={expanded ? undefined : 3}>
                        {query}
                    </Text>
                </View>
            </Pressable>
            {query.split('\n').length > 3 ? (
                <Pressable accessibilityRole="button" onPress={() => setExpanded(!expanded)}>
                    <Text style={styles.toggle}>{expanded ? 'Show less' : 'Show all'}</Text>
                </Pressable>
            ) : null}
        </View>
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
    title: { ...type.bodyStrong, color: colors.ink, marginVertical: 6 },
    queryBox: { backgroundColor: colors.sunken, padding: 8, borderRadius: 8 },
    query: { ...type.mono, color: colors.muted },
    toggle: { ...type.meta, color: colors.blue },
}))
