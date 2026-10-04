import { memo, type ReactNode, useContext, useEffect, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    ChatBubble,
    ChatBubbleContent,
    ChatMessage,
    ChatMessageContent,
    ChatMessageFooter,
    cn,
} from '@posthog/quill-primitives'

import { MarkdownMessage } from '../../messages/MarkdownMessage'
import type { ThreadItem } from '../../types/streamTypes'
import { userMessageDisplayText } from '../../utils/userMessageDisplay'
import { ThreadAttachments } from '../ThreadAttachments'
import { TurnRevealContext } from '../TurnRevealContext'
import { footerRevealClass } from './footerReveal'
import { QuillCopyButton } from './QuillFooterButton'
import { QuillFooterTimestamp } from './QuillFooterTimestamp'

// A wide table scrolls sideways under a frozen first column. Cells keep a readable width and break between words.
const ASSISTANT_TABLE_CLASS = cn(
    '[&_table]:block [&_table]:w-fit [&_table]:max-w-full [&_table]:overflow-x-auto',
    '[&_:is(th,td)]:min-w-32 [&_:is(th,td)]:[overflow-wrap:normal]',
    '[&_:is(th,td):first-child]:sticky [&_:is(th,td):first-child]:left-0 [&_:is(th,td):first-child]:z-1 [&_:is(th,td):first-child]:bg-(--background)'
)

// The copy button sits in a header bar above the code, so it never covers the first line.
const ASSISTANT_CODE_CLASS = cn(
    '[&_.CodeSnippet_pre]:!pt-10',
    '[&_.CodeSnippet_pre]:![background:linear-gradient(var(--border),var(--border))_0_2rem/100%_1px_no-repeat,linear-gradient(var(--muted),var(--muted))_0_0/100%_2rem_no-repeat,var(--card)]',
    '[&_.CodeSnippet>div:first-child]:!top-1.5 [&_.CodeSnippet>div:first-child]:!right-1.5 [&_.CodeSnippet>div:first-child]:!bg-transparent',
    '[&_.CodeSnippet>div:first-child_svg]:!text-(--muted-foreground)'
)

// A checklist starts at the text edge like a paragraph, and its read-only boxes draw at full strength. Inside quill the checkbox's lemon accent resolves to nothing, so a ticked box takes quill's primary colour.
const ASSISTANT_TASK_LIST_CLASS = cn(
    '[&_ul:has(>li>.LemonCheckbox)]:!pl-0',
    '[&_.LemonCheckbox_label]:[--box-color:var(--primary)] [&_.LemonCheckbox_svg]:!opacity-100'
)

/**
 * Clamps a user bubble to five lines with a Show more toggle. Overflow depends on wrapping width, so it
 * is measured against the clamped height and re-measured on resize, and the toggle only appears when the
 * content actually exceeds the clamp.
 */
function ClampedContent({ children }: { children: ReactNode }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [overflowing, setOverflowing] = useState(false)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const el = ref.current
        if (expanded || !el) {
            return
        }
        const observer = new ResizeObserver(() => setOverflowing(el.scrollHeight - el.clientHeight > 1))
        observer.observe(el)
        return () => observer.disconnect()
    }, [expanded])

    return (
        <>
            <div
                ref={ref}
                className={cn(
                    '[&_p]:my-0',
                    !expanded && 'max-h-[5lh] overflow-hidden',
                    !expanded && overflowing && '[mask-image:linear-gradient(to_bottom,black_45%,transparent)]'
                )}
            >
                {children}
            </div>
            {overflowing && (
                <button
                    type="button"
                    onClick={() => setExpanded(!expanded)}
                    className="mt-1 flex items-center gap-0.5 text-sm text-foreground"
                >
                    Show {expanded ? 'less' : 'more'}
                    <IconChevronDown className={cn('size-3', expanded && 'rotate-180')} />
                </button>
            )}
        </>
    )
}

export const QuillHumanMessage = memo(function QuillHumanMessage({ item }: { item: ThreadItem }): JSX.Element {
    const text = userMessageDisplayText(item.text ?? '')
    const revealed = useContext(TurnRevealContext)
    return (
        <ChatMessage align="end" data-attr="posthog-ai-human-message">
            <ChatMessageContent className="gap-1">
                {item.attachments && (
                    <div className="self-end">
                        <ThreadAttachments attachments={item.attachments} />
                    </div>
                )}
                <ChatBubble align="end" className="rounded-lg">
                    <ChatBubbleContent>
                        <ClampedContent>
                            <MarkdownMessage content={text || '*No text.*'} id={item.id} />
                        </ClampedContent>
                    </ChatBubbleContent>
                </ChatBubble>
                <ChatMessageFooter className={cn('min-h-5 items-center gap-1', footerRevealClass(revealed))}>
                    {item.startedAt !== undefined && <QuillFooterTimestamp time={item.startedAt} />}
                    {text && (
                        <QuillCopyButton value={text} label="Copy message" dataAttr="posthog-ai-human-message-copy" />
                    )}
                </ChatMessageFooter>
            </ChatMessageContent>
        </ChatMessage>
    )
})

export const QuillAssistantMessage = memo(function QuillAssistantMessage({ item }: { item: ThreadItem }): JSX.Element {
    return (
        <ChatMessage align="start">
            <ChatMessageContent className="gap-1">
                <ChatBubble variant="ghost">
                    <ChatBubbleContent>
                        <MarkdownMessage
                            content={item.text ?? ''}
                            id={item.id}
                            className={cn(ASSISTANT_TABLE_CLASS, ASSISTANT_CODE_CLASS, ASSISTANT_TASK_LIST_CLASS)}
                        />
                    </ChatBubbleContent>
                </ChatBubble>
            </ChatMessageContent>
        </ChatMessage>
    )
})
