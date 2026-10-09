import type { ReactElement } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, radii, type } from '@/ui/tokens'

interface AgentStatusCardProps {
    mark: string
    title: string
    meta?: string
    tone?: 'working' | 'stopped'
    onUndo?: () => void
    undoPending?: boolean
    testID?: string
}

export function AgentStatusCard({
    mark,
    title,
    meta,
    tone = 'working',
    onUndo,
    undoPending,
    testID,
}: AgentStatusCardProps): ReactElement {
    return (
        <View style={styles.card} testID={testID} accessibilityRole="summary">
            <View style={styles.mark}>
                <Text style={styles.markText}>{mark}</Text>
            </View>
            <View style={styles.body}>
                <View style={styles.titleRow}>
                    <Dot color={tone === 'stopped' ? colors.orange : colors.blueLight} />
                    <Text style={styles.title} numberOfLines={2}>
                        {title}
                    </Text>
                </View>
                {meta ? <Text style={styles.meta}>{meta}</Text> : null}
            </View>
            {onUndo ? (
                <Pressable44
                    onPress={onUndo}
                    disabled={undoPending}
                    accessibilityLabel="Undo your answer"
                    style={styles.undo}
                    pressedStyle={styles.undoPressed}
                    testID="decision-undo"
                >
                    <Text style={styles.undoText}>Undo</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 52,
        paddingVertical: 12,
        paddingHorizontal: 14,
        borderRadius: radii.card,
        backgroundColor: colors.ink,
    },
    mark: {
        width: 36,
        height: 36,
        borderRadius: radii.markLarge,
        backgroundColor: colors.blue,
        alignItems: 'center',
        justifyContent: 'center',
    },
    markText: {
        fontFamily: fonts.mono,
        fontSize: 13,
        fontWeight: '600',
        color: colors.background,
    },
    body: {
        flex: 1,
        minWidth: 0,
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.bodyStrong,
        color: colors.background,
        flexShrink: 1,
    },
    meta: {
        ...type.metaSmall,
        color: colors.disabled,
        marginTop: 2,
    },
    undo: {
        height: 34,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.muted,
        alignItems: 'center',
        justifyContent: 'center',
    },
    undoPressed: {
        borderColor: colors.background,
    },
    undoText: {
        fontSize: 13,
        fontWeight: '600',
        color: colors.background,
    },
})
