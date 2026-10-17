import type { ReactElement } from 'react'
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native'

import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, iconSizes, radii, type } from '@/ui/tokens'

interface AiOrgNoticeProps {
    /** `not_approved`: an admin has not allowed third-party AI. `unknown`: the app could not load the setting. */
    reason: 'not_approved' | 'unknown'
    organizationName: string | null
    /** Null hides Open settings. */
    onOpenSettings: (() => void) | null
    onCheckAgain: () => void
    checking: boolean
}

function copyFor(reason: AiOrgNoticeProps['reason'], organizationName: string | null): { title: string; body: string } {
    if (reason === 'unknown') {
        return {
            title: "Couldn't check PostHog AI access",
            body: 'Check your connection, then try again.',
        }
    }
    return {
        title: `PostHog AI is off for ${organizationName ?? 'this organization'}`,
        body: 'An organization admin needs to allow third-party AI services in the organization settings before you can chat.',
    }
}

/** Takes the composer's place while the organization does not allow PostHog AI, as the web blocks its chat. */
export function AiOrgNotice({
    reason,
    organizationName,
    onOpenSettings,
    onCheckAgain,
    checking,
}: AiOrgNoticeProps): ReactElement {
    const copy = copyFor(reason, organizationName)
    return (
        <View style={styles.notice} testID="chat-ai-org-notice">
            <Text style={styles.title} accessibilityRole="header">
                {copy.title}
            </Text>
            <Text style={styles.body}>{copy.body}</Text>
            <View style={styles.actions}>
                {onOpenSettings ? (
                    <Pressable44
                        onPress={onOpenSettings}
                        pressedBackground={colors.inkHover}
                        style={[styles.button, styles.primary]}
                        testID="chat-ai-org-settings"
                    >
                        <ExternalLinkIcon size={iconSizes.inline} color={colors.white} />
                        <Text style={styles.primaryText}>Open settings</Text>
                    </Pressable44>
                ) : null}
                <Pressable44
                    onPress={onCheckAgain}
                    disabled={checking}
                    accessibilityState={{ busy: checking, disabled: checking }}
                    pressedBackground={onOpenSettings ? colors.sunken : colors.inkHover}
                    style={[styles.button, onOpenSettings ? styles.secondary : styles.primary]}
                    testID="chat-ai-org-check-again"
                >
                    {checking ? (
                        <ActivityIndicator color={onOpenSettings ? colors.ink : colors.white} />
                    ) : (
                        <Text style={onOpenSettings ? styles.secondaryText : styles.primaryText}>Check again</Text>
                    )}
                </Pressable44>
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    notice: {
        marginHorizontal: 16,
        marginTop: 8,
        marginBottom: 8,
        padding: 16,
        gap: 6,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.background,
    },
    title: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    body: {
        ...type.bodySmall,
        color: colors.muted,
    },
    actions: {
        flexDirection: 'row',
        gap: 10,
        marginTop: 10,
    },
    button: {
        flex: 1,
        height: 44,
        flexDirection: 'row',
        gap: 8,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    primary: {
        backgroundColor: colors.ink,
    },
    primaryText: {
        ...type.buttonSmall,
        color: colors.white,
    },
    secondary: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
    },
    secondaryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
