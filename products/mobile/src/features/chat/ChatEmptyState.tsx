import type { ReactElement } from 'react'
import { Text, View } from 'react-native'

import { track } from '@/lib/analytics'
import { PostHogLogomark } from '@/ui/icons/PostHogLogomark'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { prettyWrap, radii, type } from '@/ui/tokens'

const REPORT_PROMPTS = ['What caused this?', 'Who is affected?', 'Draft a status update'] as const
const GLOBAL_PROMPTS = ['What needs me today?', 'Summarize this week', 'What did the agents ship?'] as const

interface ChatEmptyStateProps {
    reportCount: number
    suggestedPrompts?: string[]
    onPrompt: (prompt: string) => void
}

function copyFor(reportCount: number): { title: string; sub: string } {
    if (reportCount === 0) {
        return { title: 'What can I help you with?', sub: 'Ask anything, or use @ to add a report as context.' }
    }
    if (reportCount === 1) {
        return {
            title: 'Ask about this report',
            sub: 'The report is attached. Ask anything or tell the agent what to do.',
        }
    }
    return {
        title: 'Ask about these reports',
        sub: `${reportCount} reports are attached. Ask anything or tell the agent what to do.`,
    }
}

export function ChatEmptyState({ reportCount, suggestedPrompts, onPrompt }: ChatEmptyStateProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const fromReport = suggestedPrompts !== undefined && suggestedPrompts.length > 0
    const prompts: readonly string[] = fromReport ? suggestedPrompts : reportCount > 0 ? REPORT_PROMPTS : GLOBAL_PROMPTS
    const copy = copyFor(reportCount)
    // A report's own prompts are generated text, so the event names the list and the position only.
    const pick = (prompt: string, index: number): void => {
        track('mobile_chat_suggestion_picked', {
            source: fromReport ? 'report' : 'default',
            index,
            report_count: reportCount,
        })
        onPrompt(prompt)
    }
    return (
        <View style={styles.container} testID="chat-empty">
            <PostHogLogomark height={28} />
            <Text style={styles.title}>{copy.title}</Text>
            <Text style={[styles.sub, prettyWrap]}>{copy.sub}</Text>
            <View style={styles.chips}>
                {prompts.map((prompt, index) => (
                    <Pressable44
                        key={prompt}
                        onPress={() => pick(prompt, index)}
                        pressedBackground={colors.background}
                        style={styles.chip}
                    >
                        <Text style={styles.chipText} numberOfLines={2}>
                            {prompt}
                        </Text>
                    </Pressable44>
                ))}
            </View>
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        paddingHorizontal: 28,
    },
    title: {
        ...type.sheetTitleLarge,
        color: colors.ink,
        marginTop: 6,
        textAlign: 'center',
    },
    sub: {
        fontSize: 15,
        lineHeight: 21,
        color: colors.muted,
        textAlign: 'center',
    },
    chips: {
        marginTop: 8,
        flexDirection: 'row',
        flexWrap: 'wrap',
        justifyContent: 'center',
        gap: 8,
    },
    chip: {
        minHeight: 40,
        maxWidth: '100%',
        paddingHorizontal: 14,
        paddingVertical: 9,
        borderWidth: 1,
        borderColor: colors.hairline,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
        justifyContent: 'center',
    },
    chipText: {
        fontSize: 14,
        lineHeight: 19.6,
        fontWeight: '500',
        color: colors.ink,
    },
}))
