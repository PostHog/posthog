import { useRouter } from 'expo-router'
import { type ReactElement, useMemo } from 'react'
import { Platform, ScrollView, Switch, Text, View } from 'react-native'
import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { isInternalBuild } from '@/lib/environment'
import { EnvironmentRibbon } from '@/ui/EnvironmentRibbon'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles, useColors } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { AppearanceGroup } from './AppearanceGroup'
import { readAppVersion } from './appInfo'
import { DefaultPageGroup } from './DefaultPageGroup'
import { currentDefaultPageHref } from './defaultPageStore'
import { EnvironmentGroup } from './EnvironmentGroup'
import { LegalGroup } from './LegalGroup'
import { NotificationPreferencesGroup } from './NotificationPreferencesGroup'
import { ProjectSwitcher } from './ProjectSwitcher'
import { PushStatusGroup } from './PushStatusGroup'
import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'
import { SignOutSection } from './SignOutSection'

export function SettingsScreen(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    // react-native-web colors the "on" thumb from its own prop and ignores `thumbColor`. The thumb stays white in both
    // states and both schemes, like the native switch.
    const webSwitchProps = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}
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
    const scrollTitle = useScrollTitle('Settings')

    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace(currentDefaultPageHref())
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
            <ScrollView
                contentContainerStyle={[
                    styles.content,
                    {
                        paddingTop: topOffset(insets, SCREEN_CONTENT_TOP),
                        paddingBottom: bottomOffset(insets, 48),
                    },
                ]}
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                testID="settings-scroll"
            >
                <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                    Settings
                </Text>
                <EnvironmentRibbon host={sessionHost} style={styles.ribbon} />
                <DefaultPageGroup />
                {signedIn && !demo ? <ProjectSwitcher /> : null}
                {signedIn ? <PushStatusGroup /> : null}
                {signedIn || demo ? <NotificationPreferencesGroup /> : null}
                <AppearanceGroup />
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
                                    {...webSwitchProps}
                                    value={demo}
                                    onValueChange={toggleDemo}
                                    trackColor={{ true: colors.switchOn, false: colors.switchOff }}
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
                <SettingsGroup title="Account" testID="settings-account">
                    <SettingsRow label="Host" value={signedIn ? (host ?? 'Unknown') : 'Demo'} />
                    {signedIn && email ? <SettingsRow label="Signed in as" value={email} /> : null}
                    {demo ? <SettingsRow label="Project" value={viewer.projectName || 'None'} /> : null}
                </SettingsGroup>
                {isInternalBuild ? <EnvironmentGroup host={sessionHost} /> : null}
                <LegalGroup accountHost={signedIn && !demo ? host : null} />
                <SignOutSection />
            </ScrollView>
            <ScreenChrome title={scrollTitle.title} onBack={goBack} backTestID="settings-back" />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        paddingHorizontal: layout.detailGutter,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
    },
    ribbon: {
        alignSelf: 'flex-start',
        marginTop: 12,
    },
}))
