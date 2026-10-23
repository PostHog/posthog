import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { CloseIcon } from '@/ui/icons/CloseIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii } from '@/ui/tokens'

import { type ChatObjectContext, ISSUE_OBJECT_TYPE } from './objectContext'

interface ObjectContextChipProps {
    object: ChatObjectContext
    onRemove: () => void
}

export function ObjectContextChip({ object, onRemove }: ObjectContextChipProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const Icon = object.type === ISSUE_OBJECT_TYPE ? ErrorTriangleIcon : RecordingIcon
    return (
        <View style={styles.chip} testID="chat-object-chip">
            <Icon size={iconSizes.small} color={colors.muted} strokeWidth={2.2} />
            <Text style={styles.title} numberOfLines={1}>
                {object.label}
            </Text>
            <Pressable44
                onPress={onRemove}
                accessibilityLabel={`Remove ${object.label}`}
                pressedBackground={colors.hairline}
                style={styles.remove}
                hitSlop={10}
            >
                <CloseIcon size={iconSizes.small} color={colors.muted} strokeWidth={2.6} />
            </Pressable44>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 36,
        paddingLeft: 10,
        paddingRight: 6,
        borderRadius: radii.pill,
        backgroundColor: colors.sunken,
        maxWidth: '100%',
    },
    title: {
        fontSize: 14,
        lineHeight: 19.6,
        fontWeight: '600',
        color: colors.ink,
        flexShrink: 1,
    },
    remove: {
        width: 24,
        height: 24,
        borderRadius: 12,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
