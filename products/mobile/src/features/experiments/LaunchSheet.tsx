import { type ReactElement, useEffect, useState } from 'react'
import { Linking, View } from 'react-native'

import type { ExperimentApi } from '@/api/experiments'
import { actionErrorMessage } from '@/lib/errors'
import { safeHttpsUrl } from '@/lib/urls'
import { BottomSheet } from '@/ui/BottomSheet'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { createStyles, useColors } from '@/ui/theme'

import { ChangeRequestPendingError } from './actionHooks'
import { trackExperimentOpenedInWeb } from './detailAnalytics'
import { ApprovalNotice, Code, SheetButton, SheetDescription, SheetError, SheetTitle } from './FinishSheetSections'
import { launchDescription, webApprovalUrl } from './finishModel'
import { useExperimentsContext } from './hooks'

interface LaunchSheetProps {
    visible: boolean
    /** Null keeps the sheet closed, for a list row whose draft is not loaded yet. */
    experiment: ExperimentApi | null
    pending: boolean
    onClose: () => void
    /**
     * Rejects with the server's error, which the sheet shows under the description. A `ChangeRequestPendingError`
     * turns the sheet into "Needs approval" instead.
     */
    onConfirm: () => Promise<void>
}

interface LaunchApproval {
    changeRequestId: string
    alreadyPending: boolean
    at: number
}

/** A draft's one verb behind one confirmation: says exactly what goes live. */
export function LaunchSheet({ visible, experiment, pending, onClose, onConfirm }: LaunchSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { scope } = useExperimentsContext()
    const [error, setError] = useState<string | null>(null)
    const [approval, setApproval] = useState<LaunchApproval | null>(null)
    useEffect(() => {
        if (visible) {
            setError(null)
            setApproval(null)
        }
    }, [visible])
    const confirm = (): void => {
        setError(null)
        onConfirm().catch((confirmError: unknown) => {
            if (confirmError instanceof ChangeRequestPendingError) {
                setApproval({
                    changeRequestId: confirmError.changeRequestId,
                    alreadyPending: confirmError.alreadyPending,
                    at: Date.now(),
                })
                return
            }
            setError(actionErrorMessage(confirmError))
        })
    }
    const approvalUrl = approval ? safeHttpsUrl(webApprovalUrl(scope, approval.changeRequestId) ?? '') : undefined
    const flagKey = experiment ? (experiment.feature_flag?.key ?? experiment.feature_flag_key) : ''
    return (
        <BottomSheet
            visible={visible && experiment !== null}
            onClose={onClose}
            accessibilityLabel={approval ? 'Needs approval' : 'Launch this experiment?'}
            testID="experiment-launch-sheet"
        >
            {approval ? (
                <ApprovalNotice
                    alreadyPending={approval.alreadyPending}
                    at={approval.at}
                    onDone={onClose}
                    onOpenApproval={
                        approvalUrl
                            ? () => {
                                  trackExperimentOpenedInWeb({ target: 'approval' })
                                  Linking.openURL(approvalUrl).catch(() => undefined)
                              }
                            : undefined
                    }
                    testID="experiment-launch-approval"
                >
                    {approval.alreadyPending ? (
                        <>
                            Turning on <Code>{flagKey}</Code> needs an approval, and a change request for it is already
                            waiting, so no new one was sent. The experiment stays a draft. Launch it again once someone
                            approves the request on the web.
                        </>
                    ) : (
                        <>
                            Turning on <Code>{flagKey}</Code> needs an approval, so we sent a change request. The
                            experiment stays a draft. Launch it again once someone approves the request on the web.
                        </>
                    )}
                </ApprovalNotice>
            ) : (
                <>
                    <SheetTitle>Launch this experiment?</SheetTitle>
                    {experiment ? <SheetDescription line={launchDescription(experiment)} /> : null}
                    <SheetError message={error} testID="experiment-launch-error" />
                    <View style={styles.buttons}>
                        <SheetButton
                            label={pending ? 'Launching…' : 'Launch'}
                            onPress={confirm}
                            pending={pending}
                            tone="accent"
                            icon={<PlayIcon size={16} color={colors.onAccent} />}
                            testID="experiment-launch-confirm"
                        />
                        <SheetButton label="Cancel" onPress={onClose} tone="ghost" testID="experiment-launch-cancel" />
                    </View>
                </>
            )}
        </BottomSheet>
    )
}

const useStyles = createStyles(() => ({
    buttons: {
        marginTop: 20,
        gap: 8,
    },
}))
