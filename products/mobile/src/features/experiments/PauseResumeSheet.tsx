import { type ReactElement, type ReactNode, useEffect, useState } from 'react'
import { Text } from 'react-native'

import { actionErrorMessage } from '@/lib/errors'
import { BottomSheet } from '@/ui/BottomSheet'
import { createStyles } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { Code, type PrimaryTone, SheetError, SheetFooter, SheetTitle } from './FinishSheetSections'

interface ConfirmSheetProps {
    visible: boolean
    title: string
    confirmLabel: string
    pendingLabel: string
    tone: PrimaryTone
    /** The web's disabled reason, such as a missing flag. */
    reason?: string | null
    pending: boolean
    onClose: () => void
    /** Rejects with the server's error, which the sheet shows above the footer. */
    onConfirm: () => Promise<void>
    testID: string
    children: ReactNode
}

function ConfirmSheet({
    visible,
    title,
    confirmLabel,
    pendingLabel,
    tone,
    reason = null,
    pending,
    onClose,
    onConfirm,
    testID,
    children,
}: ConfirmSheetProps): ReactElement {
    const [error, setError] = useState<string | null>(null)
    useEffect(() => {
        if (visible) {
            setError(null)
        }
    }, [visible])
    const confirm = (): void => {
        setError(null)
        onConfirm().catch((confirmError: unknown) => setError(actionErrorMessage(confirmError)))
    }
    return (
        <BottomSheet visible={visible} onClose={onClose} accessibilityLabel={title} testID={testID}>
            <SheetTitle>{title}</SheetTitle>
            {children}
            <SheetError message={error} testID={`${testID}-error`} />
            <SheetFooter
                reason={pending ? null : reason}
                pending={pending}
                onCancel={onClose}
                primary={{
                    label: pending ? pendingLabel : confirmLabel,
                    onPress: confirm,
                    tone,
                    testID: `${testID}-confirm`,
                }}
            />
        </BottomSheet>
    )
}

function Paragraph({ children }: { children: ReactNode }): ReactElement {
    const styles = useStyles()
    return <Text style={styles.paragraph}>{children}</Text>
}

function Strong({ children }: { children: ReactNode }): ReactElement {
    const styles = useStyles()
    return <Text style={styles.strong}>{children}</Text>
}

interface PauseResumeSheetProps {
    visible: boolean
    mode: 'pause' | 'resume'
    /** Null when no flag is linked, which disables the button as on the web. */
    flagKey: string | null
    pending: boolean
    onClose: () => void
    onConfirm: () => Promise<void>
}

/** The web's Pause experiment and Resume experiment modals, with their wording. */
export function PauseResumeSheet({
    visible,
    mode,
    flagKey,
    pending,
    onClose,
    onConfirm,
}: PauseResumeSheetProps): ReactElement {
    const pause = mode === 'pause'
    return (
        <ConfirmSheet
            visible={visible}
            title={pause ? 'Pause experiment' : 'Resume experiment'}
            confirmLabel={pause ? 'Pause experiment' : 'Resume experiment'}
            pendingLabel={pause ? 'Pausing…' : 'Resuming…'}
            tone={pause ? 'danger' : 'ink'}
            reason={flagKey ? null : 'No feature flag linked'}
            pending={pending}
            onClose={onClose}
            onConfirm={onConfirm}
            testID={pause ? 'experiment-pause-sheet' : 'experiment-resume-sheet'}
        >
            {pause ? (
                <>
                    <Paragraph>
                        Pausing <Strong>turns off the feature flag</Strong>
                        {flagKey ? (
                            <>
                                {' '}
                                <Code>{flagKey}</Code>
                            </>
                        ) : null}
                        , so nobody sees the experiment variants. Use it when you need to stop exposing people quickly.
                    </Paragraph>
                    <Paragraph>You can resume it at any time. All collected data is kept.</Paragraph>
                </>
            ) : (
                <>
                    <Paragraph>
                        Resuming <Strong>turns the feature flag back on</Strong>, so people see the experiment variants
                        again. The experiment continues from where it was paused.
                    </Paragraph>
                    <Paragraph>All collected data is kept, and new events are tracked.</Paragraph>
                </>
            )}
        </ConfirmSheet>
    )
}

interface ArchiveSheetProps {
    visible: boolean
    pending: boolean
    onClose: () => void
    onConfirm: () => Promise<void>
}

/**
 * The web's "Archive this experiment?" dialog. Its checkbox that also disables the flag is left out: that needs
 * `feature_flag:write`, which the app does not request, so the flag is never touched from here.
 */
export function ArchiveSheet({ visible, pending, onClose, onConfirm }: ArchiveSheetProps): ReactElement {
    return (
        <ConfirmSheet
            visible={visible}
            title="Archive this experiment?"
            confirmLabel="Archive"
            pendingLabel="Archiving…"
            tone="ink"
            pending={pending}
            onClose={onClose}
            onConfirm={onConfirm}
            testID="experiment-archive-sheet"
        >
            <Paragraph>
                This hides the experiment from the list. Its feature flag does not change. You can restore it on the web
                at any time.
            </Paragraph>
        </ConfirmSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    paragraph: {
        ...type.bodySmall,
        color: colors.muted,
        marginTop: 6,
        paddingHorizontal: 4,
    },
    strong: {
        fontWeight: '600',
        color: colors.ink,
    },
}))
