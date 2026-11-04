import type { ReactElement } from 'react'
import { ActivityIndicator, Image, Text, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { PendingAttachment } from './types'

interface AttachmentChipProps {
    attachment: PendingAttachment
    uploading: boolean
    onRemove: () => void
}

export function AttachmentChip({ attachment, uploading, onRemove }: AttachmentChipProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.chip} testID="chat-attachment-chip">
            {attachment.isImage ? (
                <Image source={{ uri: attachment.uri }} style={styles.thumbnail} accessibilityIgnoresInvertColors />
            ) : (
                <DocumentIcon size={iconSizes.control} color={colors.muted} />
            )}
            <Text style={styles.name} numberOfLines={1}>
                {attachment.name}
            </Text>
            {uploading ? (
                <View style={styles.trailing}>
                    <ActivityIndicator
                        size="small"
                        color={colors.muted}
                        accessibilityLabel={`Uploading ${attachment.name}`}
                    />
                </View>
            ) : (
                <Pressable44
                    onPress={onRemove}
                    accessibilityLabel={`Remove ${attachment.name}`}
                    pressedBackground={colors.hairline}
                    style={styles.trailing}
                    hitSlop={10}
                    testID="chat-attachment-remove"
                >
                    <CloseIcon size={iconSizes.small} color={colors.muted} strokeWidth={2.6} />
                </Pressable44>
            )}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 36,
        paddingLeft: 6,
        paddingRight: 6,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        maxWidth: '100%',
    },
    thumbnail: {
        width: 24,
        height: 24,
        borderRadius: radii.markSmall,
        backgroundColor: colors.hairline,
    },
    name: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.ink,
        flexShrink: 1,
    },
    trailing: {
        width: 24,
        height: 24,
        borderRadius: 12,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
