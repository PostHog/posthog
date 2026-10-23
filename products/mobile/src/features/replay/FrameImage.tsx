import { type ReactElement, useState } from 'react'
import { ActivityIndicator, Image, type StyleProp, View, type ViewStyle } from 'react-native'

import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii } from '@/ui/tokens'

import { useFrameUrl } from './hooks'

interface FrameImageProps {
    /** Null draws the empty tile, for a session with no frame. */
    observationId: string | null
    chapter: number | null
    style?: StyleProp<ViewStyle>
    accessibilityLabel?: string
}

export function FrameImage({ observationId, chapter, style, accessibilityLabel }: FrameImageProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    // On the web build a manual redirect is opaque, so the frame URL fails and the empty tile shows.
    const frame = useFrameUrl(observationId, chapter)
    const [failedUri, setFailedUri] = useState<string | null>(null)
    const uri = frame.data && frame.data !== failedUri ? frame.data : null
    return (
        <View
            style={[styles.tile, style]}
            accessible={accessibilityLabel !== undefined}
            accessibilityRole="image"
            accessibilityLabel={accessibilityLabel}
        >
            {uri ? (
                <Image
                    source={{ uri }}
                    style={styles.image}
                    resizeMode="cover"
                    onError={() => setFailedUri(uri)}
                    accessibilityIgnoresInvertColors
                />
            ) : observationId !== null && frame.isLoading ? (
                <ActivityIndicator size="small" color={colors.tertiary} />
            ) : (
                <RecordingIcon size={iconSizes.inline} color={colors.tertiary} />
            )}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    tile: {
        overflow: 'hidden',
        borderRadius: radii.tile,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.sunken,
        alignItems: 'center',
        justifyContent: 'center',
    },
    image: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
    },
}))
