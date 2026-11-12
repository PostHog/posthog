import { Fragment, type ReactElement, useMemo, useRef, useState } from 'react'
import { Linking, Text, View } from 'react-native'

import type { ExperimentApi, ExperimentResultsRunApi } from '@/api/experiments'
import { formatClock } from '@/lib/dates'
import { safeHttpsUrl } from '@/lib/urls'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { ComposeIcon } from '@/ui/icons/ComposeIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { RocketIcon } from '@/ui/icons/RocketIcon'
import { StopCircleIcon } from '@/ui/icons/StopCircleIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import {
    type ExperimentActionsController,
    type PendingApproval,
    useArchiveAction,
    useCleanupTarget,
    useEditConclusionAction,
    useFinishAction,
    useLaunchAction,
    usePauseResumeAction,
    usePendingApproval,
} from './actionHooks'
import { trackExperimentOpenedInWeb } from './detailAnalytics'
import { EditConclusionSheet } from './EditConclusionSheet'
import { experimentStatusOf, methodOf, primaryResultOf, webFlagUrl } from './experimentModel'
import { FinishSheet } from './FinishSheet'
import { Code } from './FinishSheetSections'
import { completionLine, type FinishPreset, webApprovalUrl } from './finishModel'
import { useExperimentsContext } from './hooks'
import { LaunchSheet } from './LaunchSheet'
import { ArchiveSheet, PauseResumeSheet } from './PauseResumeSheet'

export interface ExperimentActionBarProps {
    experiment: ExperimentApi
    /** The stored results the detail shows. The finish sheet preselects the leader and suggests a conclusion from them. */
    latest: ExperimentResultsRunApi | null
    /** From `useExperimentActions()` on the detail screen. The More menu opens its sheets through the same controller. */
    actions: ExperimentActionsController
    onChat: () => void
    onToast: (text: string) => void
}

interface PillButton {
    key: string
    label: string
    Icon: (props: IconProps) => ReactElement
    onPress: () => void
}

/** `PlayIcon` defaults to `onInk` for an ink circle; the pill draws it in ink. */
function InkPlayIcon({ size, color }: IconProps): ReactElement {
    const colors = useColors()
    return <PlayIcon size={size === undefined ? undefined : size - 2} color={color ?? colors.ink} />
}

function openUrl(url: string | undefined): (() => void) | undefined {
    const safe = url ? safeHttpsUrl(url) : undefined
    return safe ? () => void Linking.openURL(safe).catch(() => undefined) : undefined
}

/**
 * The bottom bar of the experiment detail and every action sheet: Ship and End while running, Resume and End while
 * paused, Launch on a draft, and the outcome on a complete experiment, next to the round Chat button.
 */
export function ExperimentActionBar({
    experiment,
    latest,
    actions,
    onChat,
    onToast,
}: ExperimentActionBarProps): ReactElement {
    const { colors, shadows } = useTheme()
    const styles = useStyles()
    const insets = useScreenInsets()
    const { scope } = useExperimentsContext()
    const id = String(experiment.id)
    const status = experimentStatusOf(experiment)
    const primary = useMemo(() => primaryResultOf(experiment, latest), [experiment, latest])
    const method = methodOf(experiment, latest)
    const flag = experiment.feature_flag

    // The closing sheet keeps its preset and mode while it animates out.
    const lastPreset = useRef<FinishPreset>('ship')
    if (actions.sheet === 'ship' || actions.sheet === 'end') {
        lastPreset.current = actions.sheet
    }
    const lastPauseMode = useRef<'pause' | 'resume'>('pause')
    if (actions.sheet === 'pause' || actions.sheet === 'resume') {
        lastPauseMode.current = actions.sheet
    }
    const finishOpen = actions.sheet === 'ship' || actions.sheet === 'end'
    const [approval, setApproval] = useState<PendingApproval | null>(null)

    const cleanup = useCleanupTarget(id, finishOpen)
    const finish = useFinishAction(id)
    const launch = useLaunchAction(id)
    const pauseResume = usePauseResumeAction(id)
    const archive = useArchiveAction(id)
    const editConclusion = useEditConclusionAction(id)

    const openFinish = (preset: FinishPreset): void => {
        setApproval(null)
        actions.open(preset)
    }
    const done = (toast: string) => (): void => {
        actions.close()
        onToast(toast)
    }
    const openFlag = flag && scope ? openUrl(webFlagUrl(scope.host, scope.projectId, flag.id)) : undefined
    const openApproval = approval ? openUrl(webApprovalUrl(scope, approval.changeRequestId)) : undefined

    let buttons: PillButton[] = []
    if (status === 'running' || status === 'frozen') {
        buttons = [
            { key: 'ship', label: 'Ship', Icon: RocketIcon, onPress: () => openFinish('ship') },
            { key: 'end', label: 'End', Icon: StopCircleIcon, onPress: () => openFinish('end') },
        ]
    } else if (status === 'paused') {
        buttons = [
            {
                key: 'resume',
                label: 'Resume',
                Icon: InkPlayIcon,
                onPress: () => actions.open('resume'),
            },
            { key: 'end', label: 'End', Icon: StopCircleIcon, onPress: () => openFinish('end') },
        ]
    } else if (status === 'draft') {
        buttons = [
            {
                key: 'launch',
                label: 'Launch',
                Icon: InkPlayIcon,
                onPress: () => actions.open('launch'),
            },
        ]
    }
    const outcome = status === 'complete' ? completionLine(experiment) : null

    return (
        <>
            <View style={[styles.bar, { paddingBottom: bottomOffset(insets, 38) }]} testID="experiment-action-bar">
                {outcome ? (
                    <View style={styles.outcome} testID="experiment-action-outcome">
                        <Text style={styles.outcomeLabel} numberOfLines={1}>
                            {outcome.label}
                        </Text>
                        <Text style={styles.outcomeLine} numberOfLines={1}>
                            {outcome.line}
                        </Text>
                    </View>
                ) : (
                    <View style={[styles.pill, shadows.actionPill]}>
                        <View style={styles.inner}>
                            {buttons.map(({ key, label, Icon, onPress }, index) => (
                                <Fragment key={key}>
                                    {index > 0 ? <View style={styles.divider} /> : null}
                                    <Pressable44
                                        onPress={onPress}
                                        accessibilityRole="button"
                                        accessibilityLabel={label}
                                        pressedBackground={colors.background}
                                        style={styles.button}
                                        testID={`experiment-${key}`}
                                    >
                                        <Icon size={iconSizes.control} />
                                        <Text style={styles.label} numberOfLines={1}>
                                            {label}
                                        </Text>
                                    </Pressable44>
                                </Fragment>
                            ))}
                        </View>
                    </View>
                )}
                <Pressable44
                    onPress={onChat}
                    accessibilityRole="button"
                    accessibilityLabel="Chat about this experiment"
                    pressedBackground={colors.inkHover}
                    style={[styles.chat, shadows.fab]}
                    haptic="selection"
                    testID="experiment-chat"
                >
                    <ComposeIcon size={iconSizes.navigation} color={colors.onInk} />
                </Pressable44>
            </View>
            <FinishSheet
                visible={finishOpen}
                preset={lastPreset.current}
                experiment={experiment}
                primary={primary}
                method={method}
                cleanup={cleanup.state}
                onRetryCleanup={cleanup.retry}
                pending={finish.pending}
                approval={approval}
                onClose={() => {
                    if (approval) {
                        onToast(approval.alreadyPending ? 'Change request already waiting' : 'Change request sent')
                    }
                    actions.close()
                }}
                onConfirm={(request) =>
                    finish.run({
                        request,
                        preset: lastPreset.current,
                        onFinished: (toast) => done(toast)(),
                        onNeedsApproval: setApproval,
                    })
                }
                onOpenFlag={
                    openFlag
                        ? () => {
                              trackExperimentOpenedInWeb({ target: 'flag' })
                              openFlag()
                          }
                        : undefined
                }
                onOpenApproval={
                    openApproval
                        ? () => {
                              trackExperimentOpenedInWeb({ target: 'approval' })
                              openApproval()
                          }
                        : undefined
                }
            />
            <LaunchSheet
                visible={actions.sheet === 'launch'}
                experiment={experiment}
                pending={launch.pending}
                onClose={actions.close}
                onConfirm={() => launch.run(done('Experiment launched'))}
            />
            <PauseResumeSheet
                visible={actions.sheet === 'pause' || actions.sheet === 'resume'}
                mode={lastPauseMode.current}
                flagKey={flag?.key ?? null}
                pending={pauseResume.pending}
                onClose={actions.close}
                onConfirm={() =>
                    pauseResume.run(lastPauseMode.current, (outcome) =>
                        done(
                            outcome === 'needs_approval'
                                ? 'Change request sent'
                                : outcome === 'already_waiting'
                                  ? 'Change request already waiting'
                                  : lastPauseMode.current === 'pause'
                                    ? 'Experiment paused'
                                    : 'Experiment resumed'
                        )()
                    )
                }
            />
            <EditConclusionSheet
                visible={actions.sheet === 'edit_conclusion'}
                experiment={experiment}
                pending={editConclusion.pending}
                onClose={actions.close}
                onConfirm={(edit) => editConclusion.run(edit, done('Conclusion saved'))}
            />
            <ArchiveSheet
                visible={actions.sheet === 'archive'}
                pending={archive.pending}
                onClose={actions.close}
                onConfirm={() => archive.run(done('Experiment archived'))}
            />
        </>
    )
}

/**
 * "Waiting for approval" under the hypothesis while a ship waits on a change request. Renders nothing otherwise, so the
 * detail can mount it unconditionally.
 */
export function PendingApprovalBanner({ experiment }: { experiment: ExperimentApi }): ReactElement | null {
    const { colors } = useTheme()
    const styles = useStyles()
    const approval = usePendingApproval(experiment)
    if (!approval) {
        return null
    }
    return (
        <View style={styles.waiting} testID="experiment-waiting-approval">
            <ClockIcon size={18} color={colors.blue} />
            <Text style={styles.waitingText}>
                <Text style={styles.waitingStrong}>Waiting for approval.</Text>{' '}
                {approval.alreadyPending ? (
                    'A request to change this flag is already waiting.'
                ) : (
                    <>
                        Your request to ship <Code>{approval.variant}</Code> was sent at{' '}
                        {formatClock(new Date(approval.sentAt))}.
                    </>
                )}{' '}
                Nothing changes until someone approves it.
            </Text>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    bar: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        backgroundColor: colors.background,
        paddingTop: 10,
        paddingHorizontal: layout.actionBarGutter,
        borderTopWidth: 1,
        borderTopColor: colors.footerHairline,
    },
    // 52pt buttons inside a 1pt border, the same as the issue and report action pills.
    pill: {
        flex: 1,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    inner: {
        flex: 1,
        flexDirection: 'row',
        borderRadius: radii.pill,
        overflow: 'hidden',
    },
    button: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
    },
    label: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    divider: {
        width: 1,
        marginVertical: 14,
        backgroundColor: colors.hairline,
    },
    outcome: {
        flex: 1,
        minWidth: 0,
        minHeight: 54,
        justifyContent: 'center',
        paddingLeft: 6,
    },
    outcomeLabel: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    outcomeLine: {
        ...type.metaSmall,
        color: colors.secondary,
    },
    chat: {
        width: 54,
        height: 54,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    waiting: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
        marginTop: 14,
        paddingVertical: 12,
        paddingHorizontal: 14,
        borderRadius: radii.option,
        backgroundColor: colors.blueHighlight,
    },
    waitingText: {
        ...type.metaSmall,
        lineHeight: 20,
        color: colors.ink,
        flex: 1,
        minWidth: 0,
    },
    waitingStrong: {
        fontWeight: '600',
    },
}))
