import { type ReactElement, useState } from 'react'
import { Text, View } from 'react-native'
import { useProjectScope } from '@/auth/useProjectScope'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'
import { ChatVisualization } from './ChatVisualization'
import { objectWebUrl } from './objectTags'
import { openReplyUrl } from './webLinks'

export function QueryCard({ query, title }: { query: string; title?: string }): ReactElement {
    const styles = useStyles()
    const scope = useProjectScope()
    const url = scope && objectWebUrl(scope.host, scope.projectId, 'hogql', query)
    const [expanded, setExpanded] = useState(false)
    return (
        <ChatVisualization query={{ kind: 'HogQLQuery', query }} title={title || 'SQL query'}>
            <Pressable44
                accessibilityRole="link"
                disabled={!url}
                onPress={() => {
                    if (url) openReplyUrl(url, 'query_card', { objectKind: 'hogql' })
                }}
            >
                <View style={styles.queryBox}>
                    <Text style={styles.query} numberOfLines={expanded ? undefined : 3}>
                        {query}
                    </Text>
                </View>
            </Pressable44>
            {query.split('\n').length > 3 ? (
                <Pressable44 style={styles.action} accessibilityRole="button" onPress={() => setExpanded(!expanded)}>
                    <Text style={styles.toggle}>{expanded ? 'Show less' : 'Show all'}</Text>
                </Pressable44>
            ) : null}
            {url ? (
                <Pressable44
                    style={styles.action}
                    accessibilityRole="link"
                    onPress={() => openReplyUrl(url, 'query_card', { objectKind: 'hogql' })}
                >
                    <Text style={styles.toggle}>Open SQL editor</Text>
                </Pressable44>
            ) : null}
        </ChatVisualization>
    )
}
const useStyles = createStyles(({ colors }) => ({
    queryBox: { backgroundColor: colors.sunken, padding: 8, borderRadius: 8 },
    query: { ...type.mono, color: colors.muted },
    toggle: { ...type.meta, color: colors.blue },
    action: { minHeight: 34, justifyContent: 'center' },
}))
