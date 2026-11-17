import type { ReactElement, ReactNode } from 'react'
import { ScrollView, Text, View } from 'react-native'

import { openLegalLink, PRIVACY_POLICY_URL, TERMS_URL } from '@/lib/legalLinks'
import { EnvironmentRibbon } from '@/ui/EnvironmentRibbon'
import { PostHogLogo } from '@/ui/icons/PostHogLogo'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

interface SignInFrameProps {
    /** The host the environment ribbon describes. */
    ribbonHost: string | null
    /** Above the logo, such as Cancel while adding an account. */
    top?: ReactNode
    children: ReactNode
    testID: string
}

/**
 * The sign-in page around its card: the logo and card centered above the legal footer. The page scrolls when the
 * card needs more room, including with the keyboard open.
 */
export function SignInFrame({ ribbonHost, top, children, testID }: SignInFrameProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const insets = useScreenInsets()
    return (
        <ScrollView
            style={styles.screen}
            contentContainerStyle={[
                styles.content,
                { paddingTop: insets.top, paddingBottom: bottomOffset(insets, 38) },
            ]}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets
            testID={testID}
        >
            {top}
            <View style={styles.main}>
                <EnvironmentRibbon host={ribbonHost} style={styles.ribbon} />
                <View style={styles.brand}>
                    <PostHogLogo height={28} />
                </View>
                {children}
            </View>
            <View style={styles.legal}>
                <Pressable44
                    onPress={() => openLegalLink('privacy', PRIVACY_POLICY_URL, 'sign_in')}
                    accessibilityRole="link"
                    pressedBackground={colors.pressed}
                    style={styles.legalLink}
                    testID="sign-in-privacy"
                >
                    <Text style={styles.legalText}>Privacy policy</Text>
                </Pressable44>
                <Text style={styles.legalText} importantForAccessibility="no" accessibilityElementsHidden>
                    ·
                </Text>
                <Pressable44
                    onPress={() => openLegalLink('terms', TERMS_URL, 'sign_in')}
                    accessibilityRole="link"
                    pressedBackground={colors.pressed}
                    style={styles.legalLink}
                    testID="sign-in-terms"
                >
                    <Text style={styles.legalText}>Terms</Text>
                </Pressable44>
            </View>
        </ScrollView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.detailGutter,
    },
    main: {
        flexGrow: 1,
        width: '100%',
        maxWidth: 600,
        alignSelf: 'center',
        justifyContent: 'center',
        paddingVertical: 24,
    },
    ribbon: {
        alignSelf: 'center',
        marginBottom: 24,
    },
    brand: {
        alignItems: 'center',
        marginBottom: 28,
    },
    legal: {
        marginTop: 12,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
    },
    legalLink: {
        minHeight: 44,
        paddingHorizontal: 8,
        borderRadius: radii.card,
        alignItems: 'center',
        justifyContent: 'center',
    },
    legalText: {
        ...type.meta,
        color: colors.secondary,
    },
}))
