import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGitBranch, IconPlus, IconSend } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GitHogPRReviewLogicProps, gitHogPRReviewLogic } from './gitHogPRReviewLogic'
import { GitHogRepoLogicProps, gitHogRepoLogic } from './gitHogRepoLogic'

export const scene: SceneExport<GitHogPRReviewLogicProps> = {
    component: GitHogPRReviewScene,
    logic: gitHogPRReviewLogic,
    paramsToProps: ({ params: { owner, name, number } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
        number: parseInt(number ?? '0', 10),
    }),
}

// ─── Widget registry ─────────────────────────────────────────────────────────

type WidgetType = 'conversation'

const WIDGET_DEFS: Record<WidgetType, { label: string; description: string; column: 'main' | 'side' }> = {
    conversation: { label: 'Conversation', description: 'Team discussion on this PR', column: 'main' },
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Avatar({ name }: { name: string }): JSX.Element {
    const initials = name
        .split(/\s+/)
        .map((w) => w[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()
    return (
        <div className="size-8 text-sm rounded-full bg-fill-highlight-100 flex items-center justify-center font-semibold text-secondary shrink-0">
            {initials || '?'}
        </div>
    )
}

function WidgetShell({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} closeable onClose={onRemove} className="p-0 overflow-hidden">
            {children}
        </LemonCard>
    )
}

// ─── Conversation widget ──────────────────────────────────────────────────────

function ConversationWidget({ owner, name, number }: GitHogPRReviewLogicProps): JSX.Element {
    const { messages, messagesLoading, draftMessage, submitting } = useValues(
        gitHogPRReviewLogic({ owner, name, number })
    )
    const { setDraftMessage, submitMessage } = useActions(gitHogPRReviewLogic({ owner, name, number }))

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            submitMessage()
        }
    }

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between">
                <span className="font-semibold text-sm">Conversation</span>
                {!messagesLoading && <span className="text-xs text-secondary">{messages.length} messages</span>}
            </div>

            {messagesLoading ? (
                <div className="px-4 py-4 flex flex-col gap-y-3">
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-1/2" />
                </div>
            ) : messages.length === 0 ? (
                <div className="px-4 py-8 text-center text-secondary text-sm">
                    No messages yet. Be the first to comment.
                </div>
            ) : (
                messages.map((m) => (
                    <div key={m.id} className="px-4 py-4 flex gap-x-3">
                        <Avatar name={m.author_name} />
                        <div className="flex flex-col gap-y-1 flex-1 min-w-0">
                            <div className="flex items-center gap-x-2">
                                <span className="font-semibold text-sm">{m.author_name}</span>
                                <span className="text-xs text-secondary">
                                    {new Date(m.created_at).toLocaleString()}
                                </span>
                            </div>
                            <p className="text-sm text-primary my-0 leading-relaxed whitespace-pre-wrap">{m.body}</p>
                        </div>
                    </div>
                ))
            )}

            <div className="px-4 py-3 flex flex-col gap-y-2">
                <LemonTextArea
                    value={draftMessage}
                    onChange={setDraftMessage}
                    onKeyDown={handleKeyDown}
                    placeholder="Leave a comment… (⌘ Enter to send)"
                    minRows={2}
                    maxRows={8}
                />
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconSend />}
                        onClick={submitMessage}
                        loading={submitting}
                        disabledReason={!draftMessage.trim() ? 'Enter a message first' : undefined}
                    >
                        Send
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

const WIDGET_COMPONENTS: Record<WidgetType, (props: GitHogPRReviewLogicProps) => JSX.Element> = {
    conversation: ConversationWidget,
}

// ─── Scene ───────────────────────────────────────────────────────────────────

export function GitHogPRReviewScene({ owner, name, number }: GitHogPRReviewLogicProps): JSX.Element {
    const { pullRequests, pullRequestsLoading } = useValues(gitHogRepoLogic({ owner, name } as GitHogRepoLogicProps))
    const pr = pullRequests.find((p) => p.number === number)

    const [widgets, setWidgets] = useState<WidgetType[]>([])

    const addWidget = (type: WidgetType): void => setWidgets((prev) => [...prev, type])
    const removeWidget = (type: WidgetType): void => setWidgets((prev) => prev.filter((w) => w !== type))

    const available = (Object.keys(WIDGET_DEFS) as WidgetType[]).filter((k) => !widgets.includes(k))
    const mainWidgets = widgets.filter((w) => WIDGET_DEFS[w].column === 'main')

    const title = pullRequestsLoading ? `#${number}` : pr ? `#${pr.number} ${pr.title}` : `#${number}`

    return (
        <SceneContent>
            <SceneTitleSection
                name={title}
                resourceType={{ type: 'githog' }}
                actions={
                    <LemonMenu
                        items={available.map((key) => ({
                            label: WIDGET_DEFS[key].label,
                            onClick: () => addWidget(key),
                        }))}
                        closeParentPopoverOnClickInside
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            disabledReason={available.length === 0 ? 'All widgets are already visible' : undefined}
                            size="small"
                        >
                            Add widget
                        </LemonButton>
                    </LemonMenu>
                }
            />

            {pr && (
                <div className="flex items-center gap-x-3 flex-wrap text-sm -mt-2">
                    <LemonTag type={pr.state === 'open' ? 'success' : 'default'} size="small">
                        {pr.state}
                    </LemonTag>
                    <span className="text-secondary flex items-center gap-x-1">
                        <IconGitBranch className="size-3.5" />
                        {pr.head_branch}
                        <span className="text-muted mx-0.5">→</span>
                        {pr.base_branch}
                    </span>
                </div>
            )}

            {widgets.length === 0 ? (
                <div className="border-2 border-dashed rounded-lg p-16 flex flex-col items-center gap-3 text-center mt-4">
                    <p className="text-secondary text-sm my-0">Add widgets to build your review workspace</p>
                    <LemonMenu
                        items={available.map((key) => ({
                            label: WIDGET_DEFS[key].label,
                            onClick: () => addWidget(key),
                        }))}
                        closeParentPopoverOnClickInside
                    >
                        <LemonButton type="primary" icon={<IconPlus />} size="small">
                            Add widget
                        </LemonButton>
                    </LemonMenu>
                </div>
            ) : (
                <div className="flex flex-col gap-y-4 mt-2">
                    {mainWidgets.map((type) => {
                        const Widget = WIDGET_COMPONENTS[type]
                        return (
                            <WidgetShell key={type} onRemove={() => removeWidget(type)}>
                                <Widget owner={owner} name={name} number={number} />
                            </WidgetShell>
                        )
                    })}
                </div>
            )}
        </SceneContent>
    )
}

export default GitHogPRReviewScene
