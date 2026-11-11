import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { BottomSheet } from '@/ui/BottomSheet'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { ImageIcon } from '@/ui/icons/ImageIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

import type { AttachmentSource } from './types'

interface AttachMenuSheetProps {
    visible: boolean
    onPick: (source: AttachmentSource) => void
    onClose: () => void
}

/** The Attach button's two sources. The chat route is a native modal, so the sheet draws inline over the chat. */
export function AttachMenuSheet({ visible, onPick, onClose }: AttachMenuSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            paddingHorizontal={20}
            accessibilityLabel="Attach"
            testID="chat-attach-sheet"
        >
            <View style={styles.rows}>
                <Pressable44
                    onPress={() => onPick('photos')}
                    style={styles.row}
                    pressedBackground={colors.background}
                    testID="chat-attach-photos"
                >
                    <ImageIcon size={iconSizes.control} color={colors.ink} />
                    <Text style={styles.label}>Photo library</Text>
                </Pressable44>
                <Pressable44
                    onPress={() => onPick('files')}
                    style={styles.row}
                    pressedBackground={colors.background}
                    testID="chat-attach-files"
                >
                    <DocumentIcon size={iconSizes.control} color={colors.ink} />
                    <Text style={styles.label}>Choose a file</Text>
                </Pressable44>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    rows: {
        marginTop: 12,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 56,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    label: {
        ...type.label,
        color: colors.ink,
        flex: 1,
    },
}))
