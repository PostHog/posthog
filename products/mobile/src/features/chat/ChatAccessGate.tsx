import { type ReactElement, type ReactNode, useEffect, useState } from 'react'
import { ActivityIndicator, Linking, StyleSheet, View } from 'react-native'

import { track } from '@/lib/analytics'
import { useColors } from '@/ui/theme'
import { AiConsentSheet } from './AiConsentSheet'
import { AiOrgNotice } from './AiOrgNotice'
import { PRIVACY_POLICY_URL } from './aiAccess'
import { useChatAccess } from './useChatAccess'

interface ChatAccessGateProps {
    /** "Not now" on the consent sheet. The chat closes, because it cannot send without consent. */
    onDecline: () => void
    /** The composer and anything else that sends to the agent. */
    children: ReactNode
}

/** Shows `children` only once the organization allows PostHog AI and the person agreed on this device. */
export function ChatAccessGate({ onDecline, children }: ChatAccessGateProps): ReactElement {
    const colors = useColors()
    const { access, rechecking, accept, checkAgain } = useChatAccess()
    const [declined, setDeclined] = useState(false)
    const kind = access.kind

    useEffect(() => {
        if (kind === 'needs_consent') {
            track('mobile_ai_consent_shown')
        } else if (kind === 'org_blocked' || kind === 'org_unknown') {
            track('mobile_ai_org_notice_shown', { reason: kind === 'org_blocked' ? 'not_approved' : 'unknown' })
        }
    }, [kind])

    const accepted = (): void => {
        accept()
        track('mobile_ai_consent_accepted')
    }
    const decline = (): void => {
        if (declined) {
            return
        }
        setDeclined(true)
        track('mobile_ai_consent_declined')
        onDecline()
    }

    if (access.kind === 'checking') {
        return (
            <View style={styles.checking} accessibilityLabel="Checking PostHog AI access" testID="chat-access-checking">
                <ActivityIndicator color={colors.ink} />
            </View>
        )
    }
    if (access.kind === 'org_blocked' || access.kind === 'org_unknown') {
        const settingsUrl = access.kind === 'org_blocked' ? access.settingsUrl : null
        return (
            <AiOrgNotice
                reason={access.kind === 'org_blocked' ? 'not_approved' : 'unknown'}
                canApprove={access.kind === 'org_blocked' && access.canApprove}
                organizationName={access.kind === 'org_blocked' ? access.organizationName : null}
                onOpenSettings={
                    settingsUrl
                        ? () => {
                              track('mobile_ai_org_settings_opened')
                              Linking.openURL(settingsUrl).catch(() => undefined)
                          }
                        : null
                }
                onCheckAgain={checkAgain}
                checking={rechecking}
            />
        )
    }
    return (
        <>
            {access.kind === 'ready' ? children : null}
            {/* The sheet stays mounted after Continue, so it slides out while the composer appears. */}
            <AiConsentSheet
                visible={access.kind === 'needs_consent' && !declined}
                onContinue={accepted}
                onNotNow={decline}
                onOpenPrivacyPolicy={() => {
                    Linking.openURL(PRIVACY_POLICY_URL).catch(() => undefined)
                }}
            />
        </>
    )
}

const styles = StyleSheet.create({
    checking: {
        height: 64,
        alignItems: 'center',
        justifyContent: 'center',
    },
})
