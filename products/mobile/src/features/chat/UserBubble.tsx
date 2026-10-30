import { memo, type ReactElement } from 'react'
import { Image, Text, View } from 'react-native'

import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { SessionAttachment } from './session/types'

interface UserBubbleProps {
    text: string
    attachments?: readonly SessionAttachment[]
}

const THUMBNAIL_SIZE = 120

/**
 * A picked image draws from the file on this device. A file from history has no local copy, and the download
 * endpoint redirects to S3, which the app's bearer token must not follow, so it shows by name only.
 */
export const UserBubble = memo(function UserBubble({ text, attachments = [] }: UserBubbleProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const thumbnails = attachments.filter((attachment) => attachment.isImage && attachment.localUri)
    const named = attachments.filter((attachment) => !(attachment.isImage && attachment.localUri))
    return (
        <View style={styles.column} testID="user-bubble">
            {thumbnails.length > 0 ? (
                <View style={styles.row}>
                    {thumbnails.map((attachment, index) => (
                        <Image
                            key={`${attachment.artifactId ?? attachment.name}-${index}`}
                            source={{ uri: attachment.localUri }}
                            style={styles.thumbnail}
                            accessibilityLabel={attachment.name}
                            accessibilityIgnoresInvertColors
                            testID="user-bubble-thumbnail"
                        />
                    ))}
                </View>
            ) : null}
            {named.length > 0 ? (
                <View style={styles.row}>
                    {named.map((attachment, index) => (
                        <View
                            key={`${attachment.artifactId ?? attachment.name}-${index}`}
                            style={styles.file}
                            testID="user-bubble-file"
                        >
                            <DocumentIcon size={iconSizes.small} color={colors.muted} />
                            <Text style={styles.fileName} numberOfLines={1}>
                                {attachment.name}
                            </Text>
                        </View>
                    ))}
                </View>
            ) : null}
            {text ? (
                <View style={styles.bubble}>
                    <Text style={styles.text}>{text}</Text>
                </View>
            ) : null}
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    column: {
        alignSelf: 'flex-end',
        alignItems: 'flex-end',
        maxWidth: '82%',
        gap: 6,
    },
    row: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        justifyContent: 'flex-end',
        gap: 6,
    },
    thumbnail: {
        width: THUMBNAIL_SIZE,
        height: THUMBNAIL_SIZE,
        borderRadius: radii.menuRow,
        backgroundColor: colors.sunken,
    },
    file: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        maxWidth: '100%',
        paddingVertical: 6,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    fileName: {
        ...type.meta,
        color: colors.ink,
        flexShrink: 1,
    },
    bubble: {
        backgroundColor: colors.sunken,
        borderRadius: radii.menuRow,
        paddingVertical: 10,
        paddingHorizontal: 14,
    },
    text: {
        ...type.body,
        color: colors.ink,
    },
}))
