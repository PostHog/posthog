import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { ThreadAutoScroller } from 'scenes/max/components/ThreadAutoScroller'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { Thread } from 'scenes/max/Thread'

import { GitHogPullRequestDetail, GitHogPullRequestFile } from '../gitHogPRReviewLogic'

/**
 * Chat widget for asking the regular PostHog AI assistant about the current
 * PR. Quick-and-dirty hackathon variant: no sandbox, no repo checkout. We
 * just pipe the PR diff + metadata into the chat as a hidden preamble so the
 * LLM has the diff in context.
 *
 * The chat input is empty on mount. ``setSystemContext`` stashes the PR
 * preamble on ``maxThreadLogic``; the streamConversation listener prepends it
 * to ``apiData.content`` on the *first* user message only. The thread message
 * rendered in the UI uses the user's original content, so the diff never
 * shows up in the visible transcript on the way in. (On a hard reload of an
 * existing conversation the persisted user message will contain the prefix
 * — acceptable for the hackathon, fixable later by plumbing system_context
 * through to the chat agent as a SystemMessage.)
 */

// Cap on the diff size we forward to the LLM. Anthropic / OpenAI context
// windows are generous but not infinite, and PostHog's conversation API caps
// message ``content`` at 40k chars (~10k tokens). We leave a healthy headroom
// for the preamble + the user's question + the model's response.
const MAX_DIFF_CHARS = 30_000

export interface PRChatContext {
    owner: string
    repo: string
    pr: GitHogPullRequestDetail
    files: GitHogPullRequestFile[]
    diff: string | null
}

function truncateDiff(diff: string | null, files: GitHogPullRequestFile[]): string {
    if (diff && diff.length <= MAX_DIFF_CHARS) {
        return diff
    }
    if (diff && diff.length > MAX_DIFF_CHARS) {
        return diff.slice(0, MAX_DIFF_CHARS) + `\n\n[... diff truncated at ${MAX_DIFF_CHARS} chars ...]`
    }
    // Fallback: reconstruct from per-file patches if the raw diff is missing
    const parts: string[] = []
    let total = 0
    for (const f of files) {
        if (!f.patch) {
            continue
        }
        const block = `--- ${f.filename}\n${f.patch}\n`
        if (total + block.length > MAX_DIFF_CHARS) {
            parts.push(`[... remaining files truncated ...]`)
            break
        }
        parts.push(block)
        total += block.length
    }
    return parts.join('\n')
}

function buildSystemContext({ owner, repo, pr, files, diff }: PRChatContext): string {
    const truncatedDiff = truncateDiff(diff, files)
    const fileList = files.map((f) => `- ${f.filename} (${f.status}, +${f.additions}/-${f.deletions})`).join('\n')
    return [
        `You are reviewing pull request #${pr.number} in ${owner}/${repo}.`,
        '',
        `Title: ${pr.title}`,
        `Author: ${pr.author}`,
        `Branch: ${pr.head_branch} (${pr.head_sha.slice(0, 7)}) → ${pr.base_branch} (${pr.base_sha.slice(0, 7)})`,
        `State: ${pr.state}${pr.draft ? ' (draft)' : ''}`,
        `Stats: +${pr.additions} / -${pr.deletions} across ${pr.changed_files} files, ${pr.commits} commits`,
        `URL: ${pr.url}`,
        '',
        'PR description:',
        pr.body ? pr.body : '(no description)',
        '',
        'Changed files:',
        fileList || '(none)',
        '',
        'Unified diff:',
        '```diff',
        truncatedDiff || '(diff unavailable)',
        '```',
        '',
        "Answer the user's questions about this PR using only the information above.",
    ].join('\n')
}

/**
 * Sits inside ``AiFirstMaxInstance`` (via shared kea logic keys) and seeds
 * ``maxThreadLogic.systemContext`` once per PR. Re-keyed by ``head_sha`` so a
 * force-push reseeds.
 */
function ChatInitializer({ tabId, context }: { tabId: string; context: PRChatContext }): null {
    const { threadLogicKey, conversation } = useValues(maxLogic({ tabId }))
    const { setSystemContext } = useActions(maxThreadLogic({ tabId, conversationId: threadLogicKey, conversation }))
    const seededRef = useRef<string | null>(null)

    useEffect(() => {
        const fingerprint = `${context.owner}/${context.repo}#${context.pr.number}@${context.pr.head_sha}`
        if (seededRef.current === fingerprint) {
            return
        }
        seededRef.current = fingerprint
        setSystemContext(buildSystemContext(context))
    }, [context, setSystemContext])

    return null
}

/**
 * Minimal chat surface: thread + input only. Intentionally drops the
 * ``ChatHeader`` ("Open in context panel" button), the ``Intro`` block
 * ("How can I help you understand users?" + subtext), and the
 * ``SidebarQuestionInputWithSuggestions`` suggestion strip ("Try PostHog AI
 * for…") that ``AiFirstMaxInstance`` normally renders — the widget already
 * has its own header above the chat.
 */
function EmbeddedMaxChat({ tabId }: { tabId: string }): JSX.Element {
    const { threadVisible, threadLogicKey, conversation } = useValues(maxLogic({ tabId }))
    const { startNewConversation } = useActions(maxLogic({ tabId }))
    const threadProps: MaxThreadLogicProps = { tabId, conversationId: threadLogicKey, conversation }
    const hasMessages = threadVisible

    return (
        <BindLogic logic={maxLogic} props={{ tabId }}>
            <BindLogic logic={maxThreadLogic} props={threadProps}>
                <div className="flex flex-col grow overflow-hidden h-full">
                    <div className="flex flex-col grow overflow-y-auto" data-attr="githog-agent-scrollable">
                        {hasMessages ? (
                            <ThreadAutoScroller>
                                {conversation?.has_unsupported_content && (
                                    <div className="px-4 pt-4">
                                        <LemonBanner type="warning">
                                            <div className="flex items-center justify-between gap-4">
                                                <span>This thread contains content that is no longer supported.</span>
                                                <LemonButton type="primary" onClick={startNewConversation}>
                                                    Start a new thread
                                                </LemonButton>
                                            </div>
                                        </LemonBanner>
                                    </div>
                                )}
                                <Thread className="p-3" />
                            </ThreadAutoScroller>
                        ) : (
                            // Empty state: push input to the bottom
                            <div className="grow" />
                        )}
                        <div
                            className={`w-full transition-all duration-300 ease-out z-50 ${
                                hasMessages ? 'sticky bottom-0 bg-primary py-2' : 'pb-2'
                            }`}
                        >
                            {!conversation?.has_unsupported_content && <SidebarQuestionInput sidePanel />}
                        </div>
                    </div>
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export function GitHogAgentChatWidget({ context }: { context: PRChatContext }): JSX.Element {
    // Unique tabId per PR so each PR keeps its own conversation, independent
    // of the global Max chat and other PR widgets.
    const tabId = `githog-pr-${context.owner}-${context.repo}-${context.pr.number}`

    return (
        <div className="flex flex-col h-full min-h-[300px]">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                <span className="font-semibold text-sm flex items-center gap-x-2">
                    <IconSparkles className="size-4 text-accent" />
                    Ask the agent
                </span>
            </div>
            <div className="flex-1 min-h-0 flex">
                <ChatInitializer tabId={tabId} context={context} />
                <EmbeddedMaxChat tabId={tabId} />
            </div>
        </div>
    )
}
