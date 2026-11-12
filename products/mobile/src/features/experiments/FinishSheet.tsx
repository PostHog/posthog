import { type ReactElement, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { ScrollViewInstance } from 'react-native'
import { Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { useReanimatedKeyboardAnimation } from 'react-native-keyboard-controller'
import Animated from 'react-native-reanimated'

import type { ExperimentApi } from '@/api/experiments'
import { actionErrorMessage } from '@/lib/errors'
import { BottomSheet } from '@/ui/BottomSheet'
import type { NativeGesture } from '@/ui/gestureTypes'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { PendingApproval } from './actionHooks'
import type { ExperimentMethod, PrimaryResult } from './experimentModel'
import {
    ApprovalNotice,
    CardTitleText,
    CheckCard,
    Code,
    CommentField,
    ConclusionRadios,
    FieldHelp,
    FieldLabel,
    InfoBanner,
    RadioCard,
    SheetDescription,
    SheetError,
    SheetFooter,
    SheetNote,
    SheetTitle,
    Tag,
} from './FinishSheetSections'
import {
    type CleanupTargetState,
    cleanupNoteOf,
    type FinishContext,
    type FinishPreset,
    type FinishRequest,
    finishButtonLabel,
    finishContextOf,
    finishDescription,
    finishDisabledReason,
    finishFormReducer,
    finishRequestOf,
    finishShips,
    finishTitle,
    initialFinishForm,
    releaseOptions,
    variantOptions,
} from './finishModel'
import { RepositoryPicker } from './RepositoryPicker'

interface FinishSheetProps {
    visible: boolean
    preset: FinishPreset
    experiment: ExperimentApi
    primary: PrimaryResult | null
    method: ExperimentMethod
    cleanup: CleanupTargetState
    onRetryCleanup: () => void
    pending: boolean
    /** Set after a 409: the flag change waits for an approval, and the sheet says so instead of the form. */
    approval: PendingApproval | null
    onClose: () => void
    /** Rejects with the server's error, which the sheet shows above the footer. */
    onConfirm: (request: FinishRequest) => Promise<void>
    onOpenFlag?: () => void
    onOpenApproval?: () => void
}

/**
 * Ship and End: the web's `FinishExperimentModal` in full. The preset picks the starting values and the title; the
 * person can still change the variant either way.
 */
export function FinishSheet(props: FinishSheetProps): ReactElement {
    const { visible, preset, approval, onClose } = props
    const keyboard = useReanimatedKeyboardAnimation()
    const scrollGesture = useMemo(() => Gesture.Native(), [])
    const title = approval ? 'Needs approval' : preset === 'ship' ? 'Ship a variant' : 'End experiment'
    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={scrollGesture}
            keyboardHeight={keyboard.height}
            accessibilityLabel={title}
            testID="experiment-finish-sheet"
        >
            {approval ? (
                <ApprovalState approval={approval} onDone={onClose} onOpenApproval={props.onOpenApproval} />
            ) : (
                <FinishForm {...props} scrollGesture={scrollGesture} />
            )}
        </BottomSheet>
    )
}

function FinishForm({
    visible,
    preset,
    experiment,
    primary,
    method,
    cleanup,
    onRetryCleanup,
    pending,
    onClose,
    onConfirm,
    onOpenFlag,
    scrollGesture,
}: FinishSheetProps & { scrollGesture: NativeGesture }): ReactElement {
    const { colors } = useTheme()
    const styles = useStyles()
    const scroll = useRef<ScrollViewInstance>(null)
    const commentY = useRef(0)
    // Read when the sheet opens, so a results refresh behind the sheet does not move the person's picks.
    const [context, setContext] = useState<FinishContext>(() => finishContextOf(experiment, primary))
    const [form, dispatch] = useReducer(finishFormReducer, null, () => initialFinishForm(preset, context))
    const [error, setError] = useState<string | null>(null)

    const wasVisible = useRef(false)
    useEffect(() => {
        if (visible && !wasVisible.current) {
            const next = finishContextOf(experiment, primary)
            setContext(next)
            dispatch({ type: 'reset', form: initialFinishForm(preset, next) })
            setError(null)
        }
        wasVisible.current = visible
    }, [visible, preset, experiment, primary])

    const reason = finishDisabledReason(form, cleanup)
    const ships = finishShips(form, context)
    const note = cleanupNoteOf(form, cleanup)
    const options = useMemo(() => variantOptions(context, primary, method), [context, primary, method])
    const confirm = (): void => {
        if (reason || pending) {
            return
        }
        setError(null)
        onConfirm(finishRequestOf(form, context, cleanup)).catch((confirmError: unknown) =>
            setError(actionErrorMessage(confirmError))
        )
    }

    return (
        <View style={styles.content}>
            <GestureDetector gesture={scrollGesture}>
                <Animated.ScrollView
                    ref={scroll}
                    keyboardShouldPersistTaps="handled"
                    style={styles.scroll}
                    testID="experiment-finish-scroll"
                >
                    <SheetTitle>{finishTitle(form, context)}</SheetTitle>
                    <SheetDescription line={finishDescription(form, context)} />
                    {context.rolledOut ? (
                        <InfoBanner testID="experiment-finish-rolled-out">
                            <Code>{context.rolledOut}</Code> is already rolled out to 100% of {context.noun}. Ending
                            marks the experiment complete without changing the feature flag.
                        </InfoBanner>
                    ) : (
                        <>
                            {context.frozen ? (
                                <InfoBanner testID="experiment-finish-frozen">
                                    Exposure is frozen. If you end without shipping, the flag keeps serving variants
                                    only to the already-enrolled {context.noun}. Shipping a variant removes the freeze.
                                </InfoBanner>
                            ) : null}
                            <FieldLabel label="Variant to keep" optional />
                            <FieldHelp>Leave it empty to end the experiment without rolling out a variant.</FieldHelp>
                            <View
                                style={styles.group}
                                accessibilityRole="radiogroup"
                                accessibilityLabel="Variant to keep"
                            >
                                {options.map((option) => (
                                    <RadioCard
                                        key={option.key ?? 'none'}
                                        selected={form.variant === option.key}
                                        onPress={() => dispatch({ type: 'variant', variant: option.key })}
                                        disabled={pending}
                                        accessibilityLabel={
                                            option.key === null
                                                ? 'None, end without rolling out a variant'
                                                : option.leading
                                                  ? `${option.key}, leading`
                                                  : option.key
                                        }
                                        title={
                                            option.key === null ? (
                                                <CardTitleText>None, end without rolling out a variant</CardTitleText>
                                            ) : (
                                                <>
                                                    <CardTitleText mono>{option.key}</CardTitleText>
                                                    {option.leading ? <Tag label="Leading" tone="good" /> : null}
                                                </>
                                            )
                                        }
                                        meta={option.meta}
                                        testID={`experiment-finish-variant-${option.key ?? 'none'}`}
                                    />
                                ))}
                            </View>
                            {form.variant !== null ? (
                                <>
                                    <FieldLabel label="How to release this variant" />
                                    <View
                                        style={styles.group}
                                        accessibilityRole="radiogroup"
                                        accessibilityLabel="How to release this variant"
                                    >
                                        {releaseOptions(context.noun).map((option) => (
                                            <RadioCard
                                                key={option.value}
                                                selected={form.release === option.value}
                                                onPress={() => dispatch({ type: 'release', release: option.value })}
                                                disabled={pending}
                                                accessibilityLabel={
                                                    option.recommended ? `${option.label}, recommended` : option.label
                                                }
                                                title={
                                                    <CardTitleText>
                                                        {option.label}
                                                        {option.recommended ? (
                                                            <Text style={styles.recommended}> (recommended)</Text>
                                                        ) : null}
                                                    </CardTitleText>
                                                }
                                                meta={option.description}
                                                testID={`experiment-finish-release-${option.value}`}
                                            />
                                        ))}
                                    </View>
                                </>
                            ) : null}
                        </>
                    )}
                    <FieldLabel label="Conclusion" />
                    <ConclusionRadios
                        value={form.conclusion}
                        suggested={context.suggested}
                        onChange={(conclusion) => dispatch({ type: 'conclusion', conclusion })}
                        disabled={pending}
                        testID="experiment-finish-conclusion"
                    />
                    <View
                        onLayout={(event) => {
                            commentY.current = event.nativeEvent.layout.y
                        }}
                    >
                        <FieldLabel label="Comment" optional />
                        <CommentField
                            value={form.comment}
                            onChange={(comment) => dispatch({ type: 'comment', comment })}
                            editable={!pending}
                            onFocus={() => scroll.current?.scrollTo({ y: Math.max(commentY.current - 8, 0) })}
                            testID="experiment-finish-comment"
                        />
                    </View>
                    {cleanup.status !== 'unavailable' ? (
                        <>
                            <FieldLabel label="Code cleanup" />
                            <CheckCard
                                checked={form.cleanup}
                                onPress={() => dispatch({ type: 'cleanup', cleanup: !form.cleanup })}
                                disabled={note.kind === 'no_integration' || pending}
                                accessibilityLabel={`Open a draft PR removing ${context.flagKey} from your code`}
                                testID="experiment-finish-cleanup"
                            >
                                Open a draft PR removing <Code>{context.flagKey}</Code> from your code
                            </CheckCard>
                            {note.kind === 'no_integration' ? (
                                <SheetNote icon="info" testID="experiment-finish-cleanup-no-github">
                                    Connect GitHub in your project settings to open cleanup PRs
                                </SheetNote>
                            ) : null}
                            {note.kind === 'loading' ? (
                                <SheetNote icon="spinner">Checking which repository to use…</SheetNote>
                            ) : null}
                            {note.kind === 'error' ? (
                                <Pressable44
                                    onPress={onRetryCleanup}
                                    accessibilityRole="button"
                                    accessibilityLabel="Check the repository again"
                                    pressedBackground={colors.pressed}
                                    style={styles.retry}
                                    testID="experiment-finish-cleanup-retry"
                                >
                                    <SheetNote icon="info">
                                        Couldn't check which repository to use. Tap to try again.
                                    </SheetNote>
                                </Pressable44>
                            ) : null}
                            {note.kind === 'repository' ? (
                                <SheetNote icon="none">
                                    The PR will be opened in <Code>{note.repository}</Code>.
                                </SheetNote>
                            ) : null}
                            {note.kind === 'pick' ? (
                                <RepositoryPicker
                                    candidates={note.candidates}
                                    value={form.repository}
                                    onChange={(repository) => dispatch({ type: 'repository', repository })}
                                    disabled={pending}
                                />
                            ) : null}
                        </>
                    ) : null}
                    {context.rolledOut ? null : (
                        <View style={styles.flagLine} testID="experiment-finish-flag-line">
                            <Text style={styles.flagText}>
                                For finer control over the rollout, adjust the percentage and release conditions in the{' '}
                                <Code>{context.flagKey}</Code> feature flag.
                            </Text>
                            {onOpenFlag ? (
                                <Pressable44
                                    onPress={onOpenFlag}
                                    accessibilityRole="link"
                                    accessibilityLabel="Open flag on the web"
                                    style={styles.flagButton}
                                    testID="experiment-finish-open-flag"
                                >
                                    <Text style={styles.flagButtonText}>Open flag</Text>
                                    <ExternalLinkIcon size={15} />
                                </Pressable44>
                            ) : null}
                        </View>
                    )}
                    <SheetError message={error} testID="experiment-finish-error" />
                </Animated.ScrollView>
            </GestureDetector>
            <SheetFooter
                reason={pending ? null : reason}
                pending={pending}
                onCancel={onClose}
                primary={{
                    label: finishButtonLabel(form, context, pending),
                    onPress: confirm,
                    tone: ships ? 'accent' : 'ink',
                    testID: 'experiment-finish-confirm',
                }}
            />
        </View>
    )
}

function ApprovalState({
    approval,
    onDone,
    onOpenApproval,
}: {
    approval: PendingApproval
    onDone: () => void
    onOpenApproval?: () => void
}): ReactElement {
    return (
        <ApprovalNotice
            alreadyPending={approval.alreadyPending}
            at={approval.sentAt}
            onDone={onDone}
            onOpenApproval={onOpenApproval}
            testID="experiment-finish-approval"
        >
            {approval.alreadyPending ? (
                'This flag needs an approval before it changes. A change request for it is already waiting, so no new one was sent. Nothing changes until someone approves it on the web.'
            ) : (
                <>
                    This flag needs an approval before it changes. We sent a change request to ship{' '}
                    <Code>{approval.variant}</Code>. Nothing changes until someone approves it on the web.
                </>
            )}
        </ApprovalNotice>
    )
}

const useStyles = createStyles(({ colors }) => ({
    content: {
        flexShrink: 1,
        minHeight: 0,
    },
    scroll: {
        flexGrow: 0,
        flexShrink: 1,
    },
    group: {
        gap: 6,
    },
    recommended: {
        ...type.meta,
        fontWeight: '400',
        color: colors.secondary,
    },
    retry: {
        borderRadius: radii.card,
    },
    flagLine: {
        marginTop: 18,
        paddingTop: 12,
        paddingHorizontal: 14,
        paddingBottom: 2,
        borderRadius: radii.option,
        backgroundColor: colors.sunken,
    },
    flagText: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.muted,
    },
    flagButton: {
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        alignSelf: 'flex-start',
        gap: 6,
    },
    flagButtonText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
