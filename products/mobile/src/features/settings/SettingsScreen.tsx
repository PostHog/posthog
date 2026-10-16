import { useRouter } from 'expo-router'
import { type ReactElement, useMemo } from 'react'
import { Platform, StyleSheet, Switch, Text, View } from 'react-native'
import Animated, { useAnimatedScrollHandler, useReducedMotion, useSharedValue } from 'react-native-reanimated'

import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isInternalBuild } from '@/lib/environment'
import { EnvironmentRibbon } from '@/ui/EnvironmentRibbon'
import { colors, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { readAppVersion } from './appInfo'
import { EnvironmentGroup } from './EnvironmentGroup'
import { LegalGroup } from './LegalGroup'
import { ProjectSwitcher } from './ProjectSwitcher'
import { PushStatusGroup } from './PushStatusGroup'
import { SETTINGS_CHROME_ROW_HEIGHT, SETTINGS_CHROME_TOP, SETTINGS_TITLE_GAP, SettingsChrome } from './SettingsChrome'
import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'
import { SignOutSection } from './SignOutSection'

/** react-native-web colors the "on" thumb from its own prop and ignores `thumbColor`. */
const WEB_SWITCH_PROPS = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}

export function SettingsScreen(): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const viewer = useViewer()
    const host = useAuthStore((state) => state.host)
    const signedIn = useAuthStore((state) => state.signedIn)
    const email = useAuthStore((state) => state.user?.email)
    const demo = useDemoMode((state) => state.enabled)
    const setDemo = useDemoMode((state) => state.setEnabled)
    const version = useMemo(readAppVersion, [])
    const sessionHost = signedIn ? host : null
    const reduceMotion = useReducedMotion()
    const scrollY = useSharedValue(0)
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
    })

    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace('/inbox')
        }
    }
    const toggleDemo = (enabled: boolean): void => {
        track(enabled ? 'mobile_demo_started' : 'mobile_demo_ended', { from: 'settings' })
        setDemo(enabled)
        if (!enabled && !signedIn) {
            router.replace('/sign-in')
        }
    }

    return (
        <View style={styles.screen} testID="settings-screen">
            <Animated.ScrollView
                contentContainerStyle={[
                    styles.content,
                    {
                        paddingTop: topOffset(insets, SETTINGS_CHROME_TOP),
                        paddingBottom: bottomOffset(insets, 48),
                    },
                ]}
                onScroll={onScroll}
                scrollEventThrottle={16}
            >
                <View style={styles.chipSpacer} />
                {/* The accessible header, kept in reading order; transparent rather than opacity 0 because iOS accessibility skips zero-alpha views. */}
                <Text style={[styles.title, reduceMotion ? null : styles.titleHidden]} accessibilityRole="header">
                    Settings
                </Text>
                <EnvironmentRibbon host={sessionHost} style={styles.ribbon} />
                <SettingsGroup title="Account" testID="settings-account">
                    <SettingsRow label="Host" value={signedIn ? (host ?? 'Unknown') : 'Demo'} />
                    {signedIn && email ? <SettingsRow label="Signed in as" value={email} /> : null}
                    {demo ? <SettingsRow label="Project" value={viewer.projectName || 'None'} /> : null}
                </SettingsGroup>
                {signedIn && !demo ? <ProjectSwitcher /> : null}
                {signedIn ? <PushStatusGroup /> : null}
                {__DEV__ ? (
                    <SettingsGroup
                        title="Demo"
                        footer={
                            demo && signedIn
                                ? 'The inbox shows sample reports. Turn this off to see your projects.'
                                : undefined
                        }
                    >
                        <SettingsRow
                            label="Demo mode"
                            accessory={
                                <Switch
                                    {...WEB_SWITCH_PROPS}
                                    value={demo}
                                    onValueChange={toggleDemo}
                                    trackColor={{ true: colors.ink, false: colors.border }}
                                    thumbColor={colors.white}
                                    accessibilityLabel="Demo mode"
                                    testID="settings-demo-toggle"
                                />
                            }
                        />
                    </SettingsGroup>
                ) : null}
                <SettingsGroup title="App">
                    <SettingsRow label="Version" value={version} />
                </SettingsGroup>
                {isInternalBuild ? <EnvironmentGroup host={sessionHost} /> : null}
                <LegalGroup accountHost={signedIn && !demo ? host : null} />
                <SignOutSection />
            </Animated.ScrollView>
            <SettingsChrome title="Settings" scrollY={scrollY} onBack={goBack} />
        </View>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
    },
    chipSpacer: {
        height: SETTINGS_CHROME_ROW_HEIGHT,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: SETTINGS_TITLE_GAP,
    },
    titleHidden: {
        color: 'transparent',
    },
    ribbon: {
        alignSelf: 'flex-start',
        marginTop: 12,
    },
})
