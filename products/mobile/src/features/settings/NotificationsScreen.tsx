import { useRouter } from 'expo-router'
import type { ReactElement } from 'react'
import { ScrollView, Text, View } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { READING_WIDTH } from '@/ui/adaptiveLayout'
import { ScreenChrome } from '@/ui/ScreenChrome'
import { SCREEN_CONTENT_TOP } from '@/ui/screenLayout'
import { createStyles } from '@/ui/theme'
import { layout, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'
import { useScrollTitle } from '@/ui/useScrollTitle'

import { NotificationPreferencesGroup } from './NotificationPreferencesGroup'
import { PushStatusGroup } from './PushStatusGroup'

export function NotificationsScreen(): ReactElement {
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const scrollTitle = useScrollTitle('Notifications')
    const signedIn = useAuthStore((state) => state.signedIn)
    return (
        <View style={styles.screen} testID="notifications-screen">
            <ScrollView
                contentContainerStyle={[
                    styles.content,
                    { paddingTop: topOffset(insets, SCREEN_CONTENT_TOP), paddingBottom: bottomOffset(insets, 48) },
                ]}
                onScroll={scrollTitle.onScroll}
                scrollEventThrottle={16}
                testID="notifications-scroll"
            >
                <Text style={styles.title} accessibilityRole="header" onLayout={scrollTitle.onTitleLayout}>
                    Notifications
                </Text>
                {signedIn ? <PushStatusGroup /> : null}
                <NotificationPreferencesGroup />
            </ScrollView>
            <ScreenChrome
                title={scrollTitle.title}
                onBack={() => (router.canGoBack() ? router.back() : router.replace('/settings'))}
                backTestID="notifications-back"
            />
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: { flex: 1, backgroundColor: colors.background },
    content: { width: '100%', maxWidth: READING_WIDTH, alignSelf: 'center', paddingHorizontal: layout.detailGutter },
    title: { ...type.screenTitle, color: colors.ink },
}))
