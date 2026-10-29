import * as Clipboard from 'expo-clipboard'
import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, ScrollView, Text, useWindowDimensions, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'

import { track } from '@/lib/analytics'
import { POSTHOG_AGENT } from '@/model/agent'
import type { ReportView } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { ClaudeIcon } from '@/ui/icons/ClaudeIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { OpenAIIcon } from '@/ui/icons/OpenAIIcon'
import { PlusSquareIcon } from '@/ui/icons/PlusSquareIcon'
import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, radii, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { BranchPage } from './BranchPage'
import {
    type ExternalHandoffTarget,
    externalHandoffPrompt,
    handoffRepository,
    launchExternalHandoff,
} from './externalHandoff'
import { type HandoffOptionRow, HandoffOptionRows } from './HandoffOptionRows'
import { useHandoffPreferenceStore } from './handoffPreferenceStore'
import { ModelPage } from './ModelPage'
import { ModePage } from './ModePage'
import {
    defaultModelSelection,
    effectiveRuntimeAdapter,
    modeLabel,
    modelSummary,
    resolveModeForRuntimeAdapter,
} from './runOptions'
import { useRunOptionsStore } from './runOptionsStore'
import { useModelCatalogue, useRunDefaults, useRunOptionActions } from './useRunOptions'

const COPIED_MS = 1600
const EXTERNAL_AGENTS: { target: ExternalHandoffTarget; name: string; detail: string }[] = [
    { target: 'claude', name: 'Claude Code', detail: 'Open a prepared prompt in Claude Code' },
    { target: 'codex', name: 'Codex', detail: 'Open a prepared prompt in ChatGPT' },
]

type Page = 'main' | 'model' | 'mode' | 'branch'

interface HandoffSheetProps {
    visible: boolean
    report: ReportView
    onClose: () => void
    onHandOff: () => void
    /** Called after an external agent opens or the prompt is copied. */
    onExternalHandoff?: () => void
    pending: boolean
}

export function HandoffSheet({
    visible,
    report,
    onClose,
    onHandOff,
    onExternalHandoff,
    pending,
}: HandoffSheetProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [copied, setCopied] = useState(false)
    const [page, setPage] = useState<Page>('main')
    const [activeAction, setActiveAction] = useState<ExternalHandoffTarget | 'copy' | null>(null)
    const [error, setError] = useState<string | null>(null)
    const busy = useRef(false)
    const { height } = useWindowDimensions()
    const insets = useScreenInsets()
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const defaults = useRunDefaults(visible)
    const fallback = defaultModelSelection(defaults)
    const catalogue = useModelCatalogue(visible, fallback?.model)
    const options = useRunOptionsStore((state) => state.options)
    const actions = useRunOptionActions(catalogue.catalogue, defaults)
    const modelListGesture = useMemo(() => Gesture.Native(), [])
    const wasVisible = useRef(visible)

    useEffect(() => {
        if (!visible) {
            setPage('main')
            setError(null)
            setCopied(false)
            if (wasVisible.current) {
                // Picks last one sheet session, so the quick button on another report never sends them.
                useRunOptionsStore.getState().reset()
            }
        }
        wasVisible.current = visible
    }, [visible])

    useEffect(
        () => () => {
            if (wasVisible.current) {
                useRunOptionsStore.getState().reset()
            }
        },
        []
    )

    useEffect(
        () => () => {
            if (timer.current) {
                clearTimeout(timer.current)
            }
        },
        []
    )

    const runExternalAction = async (target: ExternalHandoffTarget | 'copy'): Promise<void> => {
        if (pending || busy.current) {
            return
        }
        busy.current = true
        setActiveAction(target)
        setError(null)
        try {
            if (target === 'copy') {
                await Clipboard.setStringAsync(externalHandoffPrompt(report))
                track('mobile_handoff_prompt_copied', { report_id: report.id })
                setCopied(true)
                if (timer.current) {
                    clearTimeout(timer.current)
                }
                timer.current = setTimeout(() => setCopied(false), COPIED_MS)
            } else {
                useHandoffPreferenceStore.getState().setTarget(target)
                await launchExternalHandoff(target, report, 'sheet')
            }
            onExternalHandoff?.()
        } catch (cause) {
            setError(target === 'copy' ? "Couldn't copy the prompt. Try again." : (cause as Error).message)
        } finally {
            busy.current = false
            setActiveAction(null)
        }
    }

    const disabled = pending || activeAction !== null
    const back = (): void => setPage('main')
    const runtimeAdapter = effectiveRuntimeAdapter(options, defaults)
    // Defaults that arrive after a pick can move the run to the other harness, so show the mode it will send.
    const permissionMode = resolveModeForRuntimeAdapter(runtimeAdapter, options.permissionMode)
    const rows: HandoffOptionRow[] = [
        {
            key: 'model',
            label: 'Model',
            ...(options.model === 'default'
                ? {
                      value: 'Default',
                      detail: fallback
                          ? modelSummary(catalogue.catalogue, fallback.model, fallback.reasoningEffort)
                          : undefined,
                  }
                : { value: modelSummary(catalogue.catalogue, options.model.model, options.model.reasoningEffort) }),
            onPress: () => setPage('model'),
            testID: 'handoff-option-model',
        },
        {
            key: 'mode',
            label: 'Mode',
            value: modeLabel(permissionMode),
            onPress: () => setPage('mode'),
            testID: 'handoff-option-mode',
        },
        {
            key: 'branch',
            label: 'Branch',
            value: options.branch || 'Default',
            detail: 'Repository comes from the report',
            onPress: () => setPage('branch'),
            testID: 'handoff-option-branch',
        },
    ]

    return (
        <BottomSheet
            visible={visible}
            onClose={onClose}
            scrollGesture={page === 'model' || page === 'main' ? modelListGesture : undefined}
            accessibilityLabel="Hand off to"
            testID="handoff-sheet"
        >
            {page === 'model' ? (
                <ModelPage
                    catalogue={catalogue}
                    defaults={defaults}
                    model={options.model}
                    onPickModel={actions.pickModel}
                    onPickEffort={actions.pickEffort}
                    onResetModel={actions.resetModel}
                    listGesture={modelListGesture}
                    onBack={back}
                />
            ) : page === 'mode' ? (
                <ModePage
                    runtimeAdapter={runtimeAdapter}
                    current={permissionMode}
                    onPick={(mode) => {
                        actions.pickMode(mode)
                        back()
                    }}
                    onBack={back}
                />
            ) : page === 'branch' ? (
                <BranchPage
                    branch={options.branch}
                    onChange={actions.editBranch}
                    onDone={(openedWith) => {
                        actions.finishBranch(openedWith)
                        back()
                    }}
                />
            ) : (
                <>
                    <View style={styles.titleRow}>
                        <Text style={styles.title}>Hand off to</Text>
                        <Text style={styles.hint}>Choose an agent</Text>
                    </View>
                    <GestureDetector gesture={modelListGesture}>
                        <ScrollView style={{ maxHeight: Math.max(120, height - insets.top - insets.bottom - 180) }}>
                            <View style={styles.agents}>
                                <Pressable44
                                    onPress={() => {
                                        useHandoffPreferenceStore.getState().setTarget('posthog')
                                        onHandOff()
                                    }}
                                    disabled={disabled}
                                    haptic="light"
                                    accessibilityLabel={`Hand off to ${POSTHOG_AGENT.name}`}
                                    accessibilityState={{ busy: pending, disabled }}
                                    style={styles.agent}
                                    pressedStyle={styles.agentPressed}
                                    testID="handoff-agent-posthog"
                                >
                                    <View
                                        style={styles.agentIcon}
                                        aria-hidden
                                        accessibilityElementsHidden
                                        importantForAccessibility="no-hide-descendants"
                                    >
                                        <PostHogLogomark height={18} />
                                    </View>
                                    <View style={styles.agentBody}>
                                        <Text style={styles.agentName}>{POSTHOG_AGENT.name}</Text>
                                        <Text style={styles.agentMeta}>PostHog agent · opens a PR in your repo</Text>
                                    </View>
                                </Pressable44>
                            </View>
                            <View style={styles.context}>
                                <PlusSquareIcon size={iconSizes.inline} color={colors.tertiary} />
                                <Text style={styles.contextText}>{report.contextNote}</Text>
                            </View>
                            <Text style={styles.sectionLabel}>Use your own agent</Text>
                            <View style={styles.agents}>
                                {EXTERNAL_AGENTS.map(({ target, name, detail }) => (
                                    <Pressable44
                                        key={target}
                                        onPress={() => void runExternalAction(target)}
                                        disabled={disabled}
                                        accessibilityLabel={name}
                                        accessibilityHint={detail}
                                        accessibilityState={{ busy: activeAction === target, disabled }}
                                        style={styles.agent}
                                        pressedStyle={styles.agentPressed}
                                        testID={`handoff-agent-${target}`}
                                    >
                                        <View
                                            style={styles.agentIcon}
                                            aria-hidden
                                            accessibilityElementsHidden
                                            importantForAccessibility="no-hide-descendants"
                                        >
                                            {target === 'claude' ? <ClaudeIcon /> : <OpenAIIcon />}
                                        </View>
                                        <View style={styles.agentBody}>
                                            <Text style={styles.agentName}>{name}</Text>
                                            <Text style={styles.agentMeta}>{detail}</Text>
                                        </View>
                                        {activeAction === target && <ActivityIndicator color={colors.muted} />}
                                    </Pressable44>
                                ))}
                            </View>
                            <Text style={styles.externalNote}>
                                Review the prompt before sending. Your agent needs PostHog connected to read the report.
                                {handoffRepository(report.repository)
                                    ? ` Repository: ${handoffRepository(report.repository)}.`
                                    : ' Choose the correct repository in your agent.'}
                            </Text>
                            <Text style={styles.sectionLabel}>PostHog options</Text>
                            <HandoffOptionRows rows={rows} disabled={disabled} />
                        </ScrollView>
                    </GestureDetector>
                    {error && (
                        <Text accessibilityRole="alert" style={styles.error} testID="handoff-external-error">
                            {error}
                        </Text>
                    )}
                    <Pressable44
                        onPress={() => void runExternalAction('copy')}
                        disabled={disabled}
                        accessibilityState={{ busy: activeAction === 'copy', disabled }}
                        pressedBackground={colors.background}
                        style={styles.copy}
                        accessibilityLabel={copied ? 'Copied' : 'Copy prompt'}
                        testID="copy-prompt"
                    >
                        <CopyIcon size={iconSizes.inline} color={colors.muted} />
                        <Text style={styles.copyText}>{copied ? 'Copied' : 'Copy prompt'}</Text>
                    </Pressable44>
                </>
            )}
        </BottomSheet>
    )
}

const useStyles = createStyles(({ colors }) => ({
    titleRow: {
        marginTop: 18,
        flexDirection: 'row',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        paddingHorizontal: 4,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
    },
    hint: {
        ...type.metaSmall,
        color: colors.tertiary,
    },
    agents: {
        marginTop: 12,
        gap: 4,
    },
    agent: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        minHeight: 68,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: radii.card,
        backgroundColor: colors.background,
        borderWidth: 1,
        borderColor: colors.border,
    },
    agentPressed: {
        borderColor: colors.disabled,
    },
    agentIcon: {
        width: 36,
        height: 32,
        flexShrink: 0,
        alignItems: 'center',
        justifyContent: 'center',
    },
    agentBody: {
        flex: 1,
        minWidth: 0,
    },
    agentName: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    agentMeta: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 1,
    },
    sectionLabel: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 20,
        paddingHorizontal: 4,
    },
    externalNote: {
        ...type.metaSmall,
        color: colors.muted,
        marginTop: 12,
        paddingHorizontal: 4,
    },
    error: {
        ...type.metaSmall,
        color: colors.orange,
        marginTop: 12,
    },
    context: {
        marginTop: 14,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        paddingHorizontal: 4,
    },
    contextText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
    copy: {
        marginTop: 16,
        height: 48,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
    },
    copyText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
