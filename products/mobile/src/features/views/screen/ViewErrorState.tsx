import { type ReactElement, useEffect, useState } from 'react'
import { Text } from 'react-native'

import { toError } from '@/lib/errors'
import { shortcutMatchKey } from '@/model/adapters/viewPins'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { trackViewsErrorShown } from '../analytics'
import type { PinMatch } from '../PinButton'
import { usePinActions, usePins } from '../pinHooks'
import type { ItemErrorKind } from '../viewsCache'

interface ViewErrorStateProps {
    kind: ItemErrorKind
    /** "dashboard", "insight" or "view", for the no-access and load-failure copy. */
    noun: string
    match: PinMatch
    onRetry: () => void
    onBack: () => void
}

interface ErrorCopy {
    title: string
    message: string
    testID: string
}

function copyFor(kind: ItemErrorKind, noun: string, pinned: boolean): ErrorCopy {
    switch (kind) {
        case 'deleted':
            return {
                title: 'This view was deleted',
                message: pinned ? 'Unpin it to remove it from Views.' : 'It is no longer in this project.',
                testID: 'view-deleted',
            }
        case 'no_access':
            return {
                title: `You don't have access to this ${noun}`,
                message: pinned
                    ? 'Ask a project admin to share it with you, or unpin it.'
                    : 'Ask a project admin to share it with you.',
                testID: 'view-no-access',
            }
        default:
            return {
                title: `Couldn't load this ${noun}`,
                message: 'Check your connection and try again.',
                testID: 'view-error',
            }
    }
}

/** A view with no data to show: deleted (404), no access (403), or a failed first read. */
export function ViewErrorState({ kind, noun, match, onRetry, onBack }: ViewErrorStateProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { pins } = usePins()
    const actions = usePinActions()
    const [unpinError, setUnpinError] = useState<string | null>(null)
    const key = shortcutMatchKey(match.kind, match.ref)
    const pinView = pins.data?.find((pin) => shortcutMatchKey(pin.type, pin.ref) === key)
    const gone = kind === 'deleted' || kind === 'no_access'
    const copy = copyFor(kind, noun, Boolean(pinView))
    const screen = match.kind
    useEffect(() => {
        trackViewsErrorShown({ screen, kind })
    }, [screen, kind])

    const unpin = async (): Promise<void> => {
        if (!pinView) {
            return
        }
        setUnpinError(null)
        try {
            await actions.unpin(pinView, 'header')
            onBack()
        } catch (error) {
            setUnpinError(toError(error).message)
        }
    }

    let actionLabel = 'Try again'
    let onAction = onRetry
    if (gone) {
        actionLabel = pinView ? 'Unpin' : 'Go back'
        onAction = pinView ? () => void unpin() : onBack
    }
    return (
        <>
            <StateView
                icon={<WarningIcon size={28} color={colors.tertiary} />}
                title={copy.title}
                message={copy.message}
                actionLabel={actions.pending ? undefined : actionLabel}
                onAction={onAction}
                testID={copy.testID}
            />
            {unpinError ? (
                <Text style={styles.error} accessibilityRole="alert">
                    {unpinError}
                </Text>
            ) : null}
        </>
    )
}

const useStyles = createStyles(({ colors }) => ({
    error: {
        ...type.metaSmall,
        color: colors.orange,
        textAlign: 'center',
        paddingHorizontal: 28,
        paddingBottom: 24,
    },
}))
