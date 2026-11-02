import type { ReactElement } from 'react'
import { ActivityIndicator, ScrollView, Text, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { QueuedMessage } from './messageQueue'

interface QueuedMessagesProps {
    rows: QueuedMessage[]
    held: boolean
    onRemove: (id: string) => void
    onSendNow: () => void
    sendNowDisabledReason?: string
    sendNowPending: boolean
}

export function QueuedMessages({
    rows,
    held,
    onRemove,
    onSendNow,
    sendNowDisabledReason,
    sendNowPending,
}: QueuedMessagesProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (rows.length === 0) {
        return null
    }
    const disabled = sendNowPending || sendNowDisabledReason !== undefined
    return (
        <View style={styles.banner} testID="chat-queue">
            <View style={styles.header}>
                <Text style={styles.label} accessibilityLiveRegion="polite">
                    {`${rows.length} queued${held ? ', not sent yet' : ''}`}
                </Text>
                <Pressable44
                    onPress={onSendNow}
                    disabled={disabled}
                    accessibilityLabel="Send now"
                    accessibilityHint={sendNowDisabledReason}
                    accessibilityState={{ disabled, busy: sendNowPending }}
                    pressedBackground={colors.background}
                    style={[styles.sendNow, held && styles.sendNowHeld, disabled && styles.sendNowDisabled]}
                    testID="chat-queue-send-now"
                >
                    {sendNowPending ? <ActivityIndicator size="small" color={colors.muted} /> : null}
                    <Text style={styles.sendNowLabel}>Send now</Text>
                </Pressable44>
            </View>
            {sendNowDisabledReason ? <Text style={styles.reason}>{sendNowDisabledReason}</Text> : null}
            {/* Capped so a long queue cannot push the composer off the screen. */}
            <ScrollView
                style={styles.rows}
                contentContainerStyle={styles.rowsContent}
                keyboardShouldPersistTaps="handled"
            >
                {rows.map((row) => (
                    <View key={row.id} style={styles.row} testID="chat-queue-row">
                        <Text style={styles.rowText} numberOfLines={2}>
                            {row.text}
                        </Text>
                        {row.attachments.length > 0 ? (
                            <Text style={styles.rowFiles} testID="chat-queue-row-files">
                                {row.attachments.length === 1 ? '1 file' : `${row.attachments.length} files`}
                            </Text>
                        ) : null}
                        <Pressable44
                            onPress={() => onRemove(row.id)}
                            accessibilityLabel="Remove from queue"
                            pressedBackground={colors.pressed}
                            style={styles.remove}
                            hitSlop={10}
                            testID="chat-queue-remove"
                        >
                            <CloseIcon size={iconSizes.small} color={colors.muted} />
                        </Pressable44>
                    </View>
                ))}
            </ScrollView>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    banner: {
        marginHorizontal: 10,
        marginBottom: 8,
        gap: 6,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingLeft: 6,
    },
    label: {
        ...type.meta,
        fontWeight: '600',
        color: colors.secondary,
        flexShrink: 1,
    },
    sendNow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 32,
        paddingHorizontal: 12,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    sendNowHeld: {
        borderColor: colors.border,
    },
    sendNowDisabled: {
        opacity: 0.4,
    },
    sendNowLabel: {
        fontSize: 14,
        lineHeight: 18,
        fontWeight: '600',
        color: colors.ink,
    },
    reason: {
        ...type.meta,
        color: colors.tertiary,
        paddingLeft: 6,
    },
    rows: {
        maxHeight: 152,
        flexGrow: 0,
    },
    rowsContent: {
        gap: 6,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingVertical: 8,
        paddingLeft: 12,
        paddingRight: 8,
        borderRadius: radii.tile,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
    },
    rowText: {
        ...type.metaSmall,
        color: colors.ink,
        flex: 1,
    },
    rowFiles: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
    remove: {
        width: 28,
        height: 28,
        borderRadius: 14,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
