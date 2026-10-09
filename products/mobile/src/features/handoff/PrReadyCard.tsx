import type { ReactElement } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { safeHttpsUrl } from '@/lib/urls'
import type { PullRequestView } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, fonts, prettyWrap, radii, shadows, type } from '@/ui/tokens'

interface PrReadyCardProps {
    pullRequest: PullRequestView
}

export function pullRequestTitle(pullRequest: PullRequestView): string {
    const number = pullRequest.number === undefined ? undefined : `PR #${pullRequest.number}`
    if (number && pullRequest.title) {
        return `${number} · ${pullRequest.title}`
    }
    return pullRequest.title ?? number ?? 'Pull request'
}

const STATE_LABELS: Record<PullRequestView['state'], string> = {
    open: 'open',
    draft: 'draft',
    closed: 'closed',
    merged: 'merged',
}

const REVIEW_LABELS: Record<NonNullable<PullRequestView['reviewDecision']>, string> = {
    approved: 'approved',
    changes_requested: 'changes requested',
    review_required: 'review required',
}

function repositoryName(url: string): string | undefined {
    return /github\.com\/([^/]+\/[^/]+)\/pull\//.exec(url)?.[1]
}

function statsParts(pullRequest: PullRequestView): { before: string[]; after: string[] } {
    const hasStats =
        pullRequest.filesChanged !== undefined ||
        pullRequest.additions !== undefined ||
        pullRequest.deletions !== undefined
    if (!hasStats) {
        const repository = repositoryName(pullRequest.url)
        return {
            before: [
                ...(repository ? [repository] : []),
                STATE_LABELS[pullRequest.state],
                ...(pullRequest.reviewDecision ? [REVIEW_LABELS[pullRequest.reviewDecision]] : []),
            ],
            after: pullRequest.note ? [pullRequest.note] : [],
        }
    }
    const before: string[] = []
    if (pullRequest.filesChanged !== undefined) {
        before.push(pullRequest.filesChanged === 1 ? '1 file' : `${pullRequest.filesChanged} files`)
    }
    const after: string[] = []
    if (pullRequest.reviewDecision && pullRequest.reviewDecision !== 'review_required') {
        after.push(REVIEW_LABELS[pullRequest.reviewDecision])
    }
    if (pullRequest.checksPassed) {
        after.push('checks passed')
    }
    if (pullRequest.note) {
        after.push(pullRequest.note)
    }
    return { before, after }
}

export function PrReadyCard({ pullRequest }: PrReadyCardProps): ReactElement {
    const { before, after } = statsParts(pullRequest)
    const hasDiff = pullRequest.additions !== undefined || pullRequest.deletions !== undefined
    const url = safeHttpsUrl(pullRequest.url)
    const openPullRequest = (): void => {
        if (url) {
            Linking.openURL(url).catch(() => undefined)
        }
    }
    return (
        <View style={[styles.card, shadows.card]} testID="pr-ready-card">
            <View style={styles.header}>
                <Eyebrow color={colors.blue} withDot>
                    READY FOR REVIEW
                </Eyebrow>
            </View>
            <Text style={[styles.title, prettyWrap]} lineBreakStrategyIOS="standard">
                {pullRequestTitle(pullRequest)}
            </Text>
            <Text style={styles.stats}>
                {before.join(' · ')}
                {before.length > 0 && hasDiff ? ' · ' : ''}
                {pullRequest.additions === undefined ? null : (
                    <Text style={styles.added}>+{pullRequest.additions}</Text>
                )}
                {pullRequest.additions !== undefined && pullRequest.deletions !== undefined ? ' ' : ''}
                {pullRequest.deletions === undefined ? null : (
                    <Text style={styles.removed}>−{pullRequest.deletions}</Text>
                )}
                {after.length > 0 && (before.length > 0 || hasDiff) ? ' · ' : ''}
                {after.join(' · ')}
            </Text>
            <Pressable44
                onPress={openPullRequest}
                disabled={!url}
                accessibilityRole="link"
                pressedBackground={colors.blueHover}
                style={styles.review}
                testID="review-pr"
            >
                <Text style={styles.reviewText}>Review PR</Text>
            </Pressable44>
        </View>
    )
}

const styles = StyleSheet.create({
    card: {
        gap: 12,
        padding: 16,
        borderRadius: radii.softCard,
        backgroundColor: colors.white,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    header: {
        minHeight: 28,
        justifyContent: 'center',
    },
    title: {
        fontSize: 17,
        lineHeight: 22.95,
        fontWeight: '600',
        letterSpacing: -0.17,
        color: colors.ink,
    },
    stats: {
        fontFamily: fonts.mono,
        fontSize: 12,
        lineHeight: 16.8,
        color: colors.muted,
    },
    added: {
        color: colors.diffGreen,
        fontWeight: '600',
    },
    removed: {
        color: colors.diffRed,
        fontWeight: '600',
    },
    review: {
        height: 46,
        borderRadius: radii.option,
        backgroundColor: colors.blue,
        alignItems: 'center',
        justifyContent: 'center',
    },
    reviewText: {
        ...type.buttonSmall,
        color: colors.white,
    },
})
