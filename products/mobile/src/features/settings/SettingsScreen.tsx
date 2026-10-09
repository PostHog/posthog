import { useRouter } from 'expo-router'
import { type ReactElement, useMemo } from 'react'
import { Platform, ScrollView, StyleSheet, Switch, Text, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { useViewer } from '@/auth/useViewer'
import { useDemoMode } from '@/demo/demoMode'
import { BackChip } from '@/ui/BackChip'
import { colors, layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { readAppInfo } from './appInfo'
import { ProjectSwitcher } from './ProjectSwitcher'
import { PushStatusGroup } from './PushStatusGroup'
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
    const info = useMemo(readAppInfo, [])

    const goBack = (): void => {
        if (router.canGoBack()) {
            router.back()
        } else {
            router.replace('/inbox')
        }
    }
    const toggleDemo = (enabled: boolean): void => {
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
                    { paddingTop: topOffset(insets, 58), paddingBottom: bottomOffset(insets, 48) },
                ]}
            >
                <View style={styles.top}>
                    <BackChip onPress={goBack} testID="settings-back" />
                </View>
                <Text style={styles.title} accessibilityRole="header">
                    Settings
                </Text>
                <SettingsGroup title="Account" testID="settings-account">
                    <SettingsRow label="Host" value={signedIn ? (host ?? 'Unknown') : 'Demo'} />
                    {signedIn && email ? <SettingsRow label="Signed in as" value={email} /> : null}
                    {demo ? <SettingsRow label="Project" value={viewer.projectName || 'None'} /> : null}
                </SettingsGroup>
                {signedIn && !demo ? <ProjectSwitcher /> : null}
                {signedIn ? <PushStatusGroup /> : null}
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
                <SettingsGroup title="App">
                    <SettingsRow label="Version" value={info.version} />
                    <SettingsRow label="Update channel" value={info.channel} />
                </SettingsGroup>
                <SignOutSection />
            </ScrollView>
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
    top: {
        flexDirection: 'row',
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: 20,
    },
})
