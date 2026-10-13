import * as Clipboard from 'expo-clipboard'
import { type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import { Gesture } from 'react-native-gesture-handler'

import { POSTHOG_AGENT } from '@/model/agent'
import type { ReportView } from '@/model/types'
import { BottomSheet } from '@/ui/BottomSheet'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { PlusSquareIcon } from '@/ui/icons/PlusSquareIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, radii, type } from '@/ui/tokens'

import { BranchPage } from './BranchPage'
import { type HandoffOptionRow, HandoffOptionRows } from './HandoffOptionRows'
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

type Page = 'main' | 'model' | 'mode' | 'branch'

interface HandoffSheetProps {
    visible: boolean
    report: ReportView
    onClose: () => void
    onHandOff: () => void
    pending: boolean
}

export function HandoffSheet({ visible, report, onClose, onHandOff, pending }: HandoffSheetProps): ReactElement {
    const [copied, setCopied] = useState(false)
    const [page, setPage] = useState<Page>('main')
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

    const copyPrompt = async (): Promise<void> => {
        await Clipboard.setStringAsync(report.prompt).catch(() => undefined)
        setCopied(true)
        if (timer.current) {
            clearTimeout(timer.current)
        }
        timer.current = setTimeout(() => setCopied(false), COPIED_MS)
    }

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
            scrollGesture={page === 'model' ? modelListGesture : undefined}
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
                        <Text style={styles.hint}>Tap to send</Text>
                    </View>
                    <HandoffOptionRows rows={rows} disabled={pending} />
                    <View style={styles.agents}>
                        <Pressable44
                            onPress={onHandOff}
                            disabled={pending}
                            haptic="light"
                            accessibilityLabel={`Hand off to ${POSTHOG_AGENT.name}`}
                            accessibilityState={{ busy: pending, disabled: pending }}
                            style={styles.agent}
                            pressedStyle={styles.agentPressed}
                            testID="handoff-agent-posthog"
                        >
                            <View style={styles.mark}>
                                <Text style={styles.markText}>{POSTHOG_AGENT.mark}</Text>
                            </View>
                            <View style={styles.agentBody}>
                                <Text style={styles.agentName}>{POSTHOG_AGENT.name}</Text>
                                <Text style={styles.agentMeta}>PostHog agent · opens a PR in your repo</Text>
                            </View>
                        </Pressable44>
                    </View>
                    <View style={styles.context}>
                        <PlusSquareIcon size={15} color={colors.tertiary} />
                        <Text style={styles.contextText}>{report.contextNote}</Text>
                    </View>
                    <Pressable44
                        onPress={() => void copyPrompt()}
                        pressedBackground={colors.background}
                        style={styles.copy}
                        accessibilityLabel={copied ? 'Copied' : 'Copy prompt'}
                        testID="copy-prompt"
                    >
                        <CopyIcon size={16} color={colors.muted} />
                        <Text style={styles.copyText}>{copied ? 'Copied' : 'Copy prompt'}</Text>
                    </Pressable44>
                </>
            )}
        </BottomSheet>
    )
}

const styles = StyleSheet.create({
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
        // 60pt content box plus 8pt padding and a 1pt border on each side.
        minHeight: 78,
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
    mark: {
        width: 38,
        height: 38,
        borderRadius: radii.tile,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    markText: {
        fontFamily: fonts.mono,
        fontSize: 13,
        fontWeight: '600',
        color: colors.white,
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
        backgroundColor: colors.white,
    },
    copyText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
})
