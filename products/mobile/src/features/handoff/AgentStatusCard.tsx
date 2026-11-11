import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface AgentStatusCardProps {
    title: string
    meta?: string
    tone?: 'working' | 'idle' | 'stopped'
    onOpenChat?: () => void
    onUndo?: () => void
    undoPending?: boolean
    testID?: string
}

export function AgentStatusCard({
    title,
    meta,
    tone = 'working',
    onOpenChat,
    onUndo,
    undoPending,
    testID,
}: AgentStatusCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card} testID={testID}>
            <Pressable44
                onPress={onOpenChat}
                disabled={!onOpenChat}
                accessibilityRole={onOpenChat ? 'button' : 'summary'}
                accessibilityLabel={onOpenChat ? `View task activity in task chat: ${title}` : undefined}
                pressedBackground={colors.pressOverlay}
                style={styles.body}
                hitSlop={0}
            >
                <View style={styles.titleRow}>
                    <Dot color={tone === 'working' ? colors.blue : colors.tertiary} />
                    <Text style={styles.title} numberOfLines={1}>
                        {title}
                    </Text>
                    {onOpenChat ? (
                        <View style={styles.taskChat}>
                            <Text style={styles.taskChatText}>Task chat</Text>
                            <ChevronRightIcon size={iconSizes.small} color={colors.muted} />
                        </View>
                    ) : null}
                </View>
                {meta ? (
                    <Text style={styles.meta} numberOfLines={1} ellipsizeMode="tail">
                        {meta}
                    </Text>
                ) : null}
            </Pressable44>
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

const useStyles = createStyles(({ colors }) => ({
    card: {
        flexDirection: 'row',
        alignItems: 'center',
        minHeight: 52,
        backgroundColor: colors.surface,
    },
    body: {
        flex: 1,
        minWidth: 0,
        paddingVertical: 8,
        paddingHorizontal: 12,
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.ink,
        flex: 1,
        flexShrink: 1,
    },
    meta: {
        ...type.meta,
        color: colors.muted,
        marginTop: 2,
    },
    taskChat: { flexDirection: 'row', alignItems: 'center', gap: 2 },
    taskChatText: { ...type.meta, color: colors.muted },
    undo: {
        height: 34,
        marginRight: 14,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.muted,
        alignItems: 'center',
        justifyContent: 'center',
    },
    undoPressed: {
        borderColor: colors.ink,
    },
    undoText: {
        fontSize: 13,
        fontWeight: '600',
        color: colors.ink,
    },
}))
