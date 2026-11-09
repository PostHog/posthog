import * as Clipboard from 'expo-clipboard'
import { type ReactElement, useRef, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface CopyMessageButtonProps {
    text: string
    messageRole: 'user' | 'assistant'
}

export function CopyMessageButton({ text, messageRole }: CopyMessageButtonProps): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    const pending = useRef(false)
    const [feedback, setFeedback] = useState<{
        text: string
        status: 'copying' | 'copied' | 'error'
    } | null>(null)
    const status = feedback?.text === text ? feedback.status : undefined

    const copy = async (): Promise<void> => {
        if (pending.current) return
        pending.current = true
        setFeedback({ text, status: 'copying' })
        const properties = { message_role: messageRole, text_length: text.length, client_surface: 'mobile' }
        track('mobile_chat_message_copy_pressed', properties)
        try {
            const copied = await Clipboard.setStringAsync(text)
            setFeedback({ text, status: copied ? 'copied' : 'error' })
            track(copied ? 'mobile_chat_message_copied' : 'mobile_chat_message_copy_failed', properties)
        } catch {
            setFeedback({ text, status: 'error' })
            track('mobile_chat_message_copy_failed', properties)
        } finally {
            pending.current = false
        }
    }

    if (!text.trim()) return null

    return (
        <View style={styles.actions}>
            <Pressable44
                onPress={() => void copy()}
                disabled={status === 'copying'}
                accessibilityLabel={status === 'copied' ? 'Message copied' : 'Copy message text'}
                accessibilityLiveRegion="polite"
                accessibilityState={{ busy: status === 'copying', disabled: status === 'copying' }}
                pressedBackground={colors.pressed}
                style={styles.button}
                testID="chat-copy-message"
            >
                {status === 'copying' ? (
                    <ActivityIndicator size="small" color={colors.secondary} />
                ) : status === 'copied' ? (
                    <CheckIcon size={iconSizes.small} color={colors.secondary} />
                ) : (
                    <CopyIcon size={iconSizes.small} color={colors.secondary} />
                )}
            </Pressable44>
            {status === 'error' ? (
                <Text style={styles.error} accessibilityRole="alert">
                    Couldn't copy the message. Try again.
                </Text>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    actions: { alignItems: 'flex-start', gap: 4 },
    button: {
        alignItems: 'center',
        justifyContent: 'center',
        width: 32,
        minHeight: 32,
        borderRadius: radii.markSmall,
    },
    error: { ...type.meta, color: colors.orange },
}))
