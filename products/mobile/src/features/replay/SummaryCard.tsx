import type { ReactElement, ReactNode } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import type { OrgAiStatus } from '@/features/chat/aiAccess'
import { formatClock, formatMonthDay } from '@/lib/dates'
import { Eyebrow } from '@/ui/Eyebrow'
import { LockIcon } from '@/ui/icons/LockIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, prettyWrap, radii, type } from '@/ui/tokens'

import type { SummaryCardState } from './hooks'
import type { SessionSummary } from './replayModel'

interface SummaryCardProps {
    card: SummaryCardState
    aiStatus: OrgAiStatus
    pending: boolean
    onSummarize: () => void
    onCheckAgain: () => void
}

export function SummaryCard({ card, aiStatus, pending, onSummarize, onCheckAgain }: SummaryCardProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card} testID={`session-summary-${card.kind}`}>
            <Eyebrow>Summary</Eyebrow>
            <SummaryBody
                card={card}
                aiStatus={aiStatus}
                pending={pending}
                onSummarize={onSummarize}
                onCheckAgain={onCheckAgain}
            />
        </View>
    )
}

function SummaryBody({ card, aiStatus, pending, onSummarize, onCheckAgain }: SummaryCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    switch (card.kind) {
        case 'loading':
            return (
                <View style={styles.loading} accessibilityLabel="Loading the summary" accessibilityRole="progressbar">
                    <ActivityIndicator color={colors.tertiary} />
                </View>
            )
        case 'error':
            return (
                <Message title="Couldn't load the summary" text="Check your connection and try again.">
                    <CardButton label="Try again" onPress={card.retry} testID="session-summary-retry" />
                </Message>
            )
        case 'ready':
            return <ReadySummary summary={card.summary} />
        case 'summarizing':
            return (
                <View accessibilityLiveRegion="polite">
                    <View style={styles.titleRow}>
                        <ActivityIndicator size="small" color={colors.ink} />
                        <Text style={styles.title}>Summarizing</Text>
                    </View>
                    <Text style={styles.text}>This usually takes under a minute. You can keep reading meanwhile.</Text>
                </View>
            )
        case 'timed_out':
            return (
                <Message title="Still working" text="Check back in a minute.">
                    <CardButton label="Check again" onPress={onCheckAgain} testID="session-summary-check-again" />
                </Message>
            )
        case 'failed':
            return (
                <Message
                    title="The summary didn't work for this session"
                    text={[card.reason, 'To watch it, use Open full replay at the top.'].filter(Boolean).join(' ')}
                />
            )
        case 'none':
            if (aiStatus === 'not_approved') {
                return (
                    <View>
                        <View style={styles.titleRow}>
                            <LockIcon size={iconSizes.inline} color={colors.muted} />
                            <Text style={styles.title}>AI summaries are off for this organization</Text>
                        </View>
                        <Text style={styles.text}>
                            Review AI access to summarize this session. To watch the full recording now, use Open full
                            replay at the top.
                        </Text>
                        <CardButton
                            label="Review AI access"
                            onPress={onSummarize}
                            disabled={pending}
                            testID="session-summary-ai-access"
                        />
                    </View>
                )
            }
            return (
                <Message
                    title="No summary yet"
                    text="Replay Vision hasn't summarized this session. A summary adds a title, chapters and frames."
                >
                    <CardButton
                        label="Summarize this session"
                        icon={<SparklesIcon size={iconSizes.control} />}
                        onPress={onSummarize}
                        disabled={pending}
                        testID="session-summarize"
                    />
                    {card.notice ? (
                        <Text style={styles.notice} accessibilityRole="alert">
                            {card.notice}
                        </Text>
                    ) : (
                        <Text style={styles.note}>Uses Replay Vision credits</Text>
                    )}
                </Message>
            )
    }
}

const NOTABILITY_BARS = 5

function ReadySummary({ summary }: { summary: SessionSummary }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const filled = summary.notability === null ? 0 : Math.round(summary.notability * NOTABILITY_BARS)
    const scanned = summary.scannedAt ? new Date(summary.scannedAt) : null
    return (
        <View>
            {summary.text ? (
                <Text style={[styles.summary, prettyWrap]} lineBreakStrategyIOS="standard">
                    {summary.text}
                </Text>
            ) : null}
            {summary.notability !== null ? (
                <View style={styles.worth}>
                    <View style={styles.bars} accessible={false}>
                        {Array.from({ length: NOTABILITY_BARS }, (_, index) => (
                            <View
                                // biome-ignore lint/suspicious/noArrayIndexKey: the bars never reorder.
                                key={index}
                                style={[
                                    styles.bar,
                                    { backgroundColor: index < filled ? colors.orange : colors.border },
                                ]}
                            />
                        ))}
                    </View>
                    <Text style={styles.worthText}>
                        <Text style={styles.worthLabel}>Worth watching</Text>
                        {summary.notabilityReason ? ` · ${summary.notabilityReason}` : ''}
                    </Text>
                </View>
            ) : null}
            {scanned ? (
                <MonoText color={colors.tertiary} style={styles.footer}>
                    {`Replay Vision · scanned ${formatMonthDay(scanned)}, ${formatClock(scanned)}`}
                </MonoText>
            ) : null}
        </View>
    )
}

function Message({ title, text, children }: { title: string; text: string; children?: ReactNode }): ReactElement {
    const styles = useStyles()
    return (
        <View>
            <Text style={styles.title}>{title}</Text>
            <Text style={styles.text}>{text}</Text>
            {children}
        </View>
    )
}

interface CardButtonProps {
    label: string
    icon?: ReactNode
    onPress: () => void
    disabled?: boolean
    testID: string
}

function CardButton({ label, icon, onPress, disabled = false, testID }: CardButtonProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel={label}
            accessibilityState={{ disabled }}
            pressedBackground={colors.sunken}
            style={[styles.button, disabled && styles.buttonDisabled]}
            testID={testID}
        >
            {disabled ? <ActivityIndicator size="small" color={colors.ink} /> : icon}
            <Text style={styles.buttonText}>{label}</Text>
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        marginTop: 20,
        padding: 16,
        gap: 10,
        borderWidth: 1,
        borderColor: colors.border,
        borderRadius: radii.softCard,
        backgroundColor: colors.surface,
    },
    loading: {
        minHeight: 64,
        alignItems: 'center',
        justifyContent: 'center',
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    text: {
        ...type.bodySmall,
        color: colors.muted,
        marginTop: 4,
    },
    summary: {
        ...type.body,
        lineHeight: 24,
        color: colors.ink,
    },
    worth: {
        marginTop: 12,
        paddingTop: 12,
        borderTopWidth: 1,
        borderTopColor: colors.hairline,
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 10,
    },
    bars: {
        flexDirection: 'row',
        gap: 2,
        marginTop: 4,
    },
    bar: {
        width: 4,
        height: 12,
        borderRadius: 1,
    },
    worthText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
    worthLabel: {
        fontWeight: '600',
        color: colors.ink,
    },
    footer: {
        marginTop: 10,
    },
    button: {
        marginTop: 14,
        alignSelf: 'flex-start',
        minHeight: 44,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 18,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    buttonDisabled: {
        opacity: 0.6,
    },
    buttonText: {
        ...type.button,
        color: colors.ink,
    },
    note: {
        ...type.meta,
        color: colors.tertiary,
        marginTop: 10,
    },
    notice: {
        ...type.meta,
        color: colors.orange,
        marginTop: 10,
    },
}))
