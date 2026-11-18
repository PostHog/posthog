import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { BottomSheet } from '@/ui/BottomSheet'
import { Eyebrow } from '@/ui/Eyebrow'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'

interface AiConsentSheetProps {
    visible: boolean
    pending?: boolean
    onContinue: () => void
    /** Also runs when the sheet is dragged down or the scrim is tapped. */
    onNotNow: () => void
    onOpenPrivacyPolicy: () => void
}

/** The shared disclosure for chat, task handoff and replay summarization. */
export function AiConsentSheet({
    visible,
    pending = false,
    onContinue,
    onNotNow,
    onOpenPrivacyPolicy,
}: AiConsentSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <BottomSheet visible={visible} onClose={onNotNow} accessibilityLabel="PostHog AI" testID="chat-ai-consent">
            <View style={styles.content}>
                <Text style={styles.title} accessibilityRole="header">
                    Before you use PostHog AI
                </Text>
                <View style={styles.section}>
                    <Eyebrow>What is sent</Eyebrow>
                    <Text style={styles.body}>
                        Your messages, attached reports, files and photos, selected session recordings, and project data
                        used by the agent. The data sent depends on the action you choose.
                    </Text>
                </View>
                <View style={styles.section}>
                    <Eyebrow>Where it goes</Eyebrow>
                    <Text style={styles.body}>
                        PostHog AI, which uses third-party model providers such as Anthropic and OpenAI to process it.
                    </Text>
                </View>
                <Pressable44
                    onPress={onOpenPrivacyPolicy}
                    accessibilityRole="link"
                    pressedBackground={colors.sunken}
                    style={styles.link}
                    testID="chat-ai-consent-privacy"
                >
                    <Text style={styles.linkText}>Privacy policy</Text>
                    <ExternalLinkIcon size={iconSizes.small} color={colors.blue} />
                </Pressable44>
                <View style={styles.actions}>
                    <Pressable44
                        onPress={onNotNow}
                        pressedBackground={colors.sunken}
                        style={[styles.button, styles.secondary]}
                        testID="chat-ai-consent-not-now"
                    >
                        <Text style={styles.secondaryText}>Not now</Text>
                    </Pressable44>
                    <Pressable44
                        onPress={onContinue}
                        pressedBackground={colors.inkHover}
                        style={[styles.button, styles.primary]}
                        testID="chat-ai-consent-continue"
                        disabled={pending}
                        accessibilityState={{ disabled: pending, busy: pending }}
                    >
                        {pending ? (
                            <ActivityIndicator color={colors.onInk} />
                        ) : (
                            <Text style={styles.primaryText}>Continue</Text>
                        )}
                    </Pressable44>
                </View>
            </View>
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        paddingTop: 16,
        gap: 16,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    section: {
        gap: 6,
    },
    body: {
        ...type.bodySmall,
        color: colors.muted,
    },
    link: {
        alignSelf: 'flex-start',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        minHeight: 32,
        marginLeft: -8,
        paddingHorizontal: 8,
        borderRadius: radii.tile,
    },
    linkText: {
        ...type.bodySmallStrong,
        color: colors.blue,
    },
    actions: {
        flexDirection: 'row',
        gap: 10,
        marginTop: 4,
    },
    button: {
        flex: 1,
        height: 48,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    primary: {
        backgroundColor: colors.ink,
    },
    primaryText: {
        ...type.button,
        color: colors.onInk,
    },
    secondary: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    secondaryText: {
        ...type.button,
        color: colors.ink,
    },
}))
