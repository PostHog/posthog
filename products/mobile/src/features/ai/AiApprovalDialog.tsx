import type { ReactElement } from 'react'
import { ActivityIndicator, Linking, Modal, View } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'

import { AiConsentSheet } from '@/features/chat/AiConsentSheet'
import { AiOrgNotice } from '@/features/chat/AiOrgNotice'
import { PRIVACY_POLICY_URL } from '@/features/chat/aiAccess'
import { BottomSheet } from '@/ui/BottomSheet'
import { OverlayHost } from '@/ui/OverlayPortal'
import { createStyles } from '@/ui/theme'

import { cancelAiApproval, checkAiApproval, useAiApprovalStore } from './aiApproval'

export function AiApprovalDialog(): ReactElement | null {
    const request = useAiApprovalStore((state) => state.request)
    const styles = useStyles()
    const access = request?.access
    if (!request || !access || access.kind === 'ready') {
        return null
    }
    return (
        <Modal transparent visible onRequestClose={cancelAiApproval} presentationStyle="overFullScreen">
            <GestureHandlerRootView style={styles.root}>
                <OverlayHost>
                    {access.kind === 'needs_consent' ? (
                        <AiConsentSheet
                            visible
                            pending={request.checking}
                            onContinue={() => void checkAiApproval(true)}
                            onNotNow={cancelAiApproval}
                            onOpenPrivacyPolicy={() => void Linking.openURL(PRIVACY_POLICY_URL).catch(() => undefined)}
                        />
                    ) : (
                        <BottomSheet visible onClose={cancelAiApproval} accessibilityLabel="PostHog AI access">
                            <AiOrgNotice
                                reason={access.kind === 'org_unknown' ? 'unknown' : 'not_approved'}
                                organizationName={access.kind === 'org_blocked' ? access.organizationName : null}
                                canApprove={access.kind === 'org_blocked' && access.canApprove}
                                onOpenSettings={
                                    access.kind === 'org_blocked' && access.settingsUrl
                                        ? () =>
                                              void Linking.openURL(access.settingsUrl as string).catch(() => undefined)
                                        : null
                                }
                                onCheckAgain={() => void checkAiApproval()}
                                checking={request.checking}
                                onCancel={cancelAiApproval}
                            />
                        </BottomSheet>
                    )}
                    {request.checking ? (
                        <View accessibilityLabel="Checking AI approval" pointerEvents="none" style={styles.progress}>
                            <ActivityIndicator />
                        </View>
                    ) : null}
                </OverlayHost>
            </GestureHandlerRootView>
        </Modal>
    )
}

const useStyles = createStyles(() => ({ root: { flex: 1 }, progress: { position: 'absolute', top: 60, right: 24 } }))
