/**
 * `<EditWithAIButton>` — a small pill that seeds the concierge with a
 * pre-filled prompt and opens the dock. Use wherever the user might
 * want to edit something but doesn't want to type the request from
 * scratch (spec sections, bundle files, secrets, new-agent flow).
 *
 * The button itself doesn't do anything clever — it calls
 * `dockStore.startConcierge({ prompt, agentSlug })`. The concierge
 * dock observes the seed and either auto-executes (no active session)
 * or pops a confirm dialog (active session — user picks between
 * "continue this chat" and "start fresh").
 *
 * Style is intentionally muted so the buttons can sit inline next to
 * editable sections without dominating the page. The Sparkles icon
 * gives them a consistent "AI affordance" cue across the app.
 */

'use client'

import { SparklesIcon } from 'lucide-react'

import { useDockLayout } from '@/lib/useDockLayout'

import { useDockStore } from './dock-context'

export interface EditWithAIButtonProps {
    /** Seed prompt — what the concierge sees as the first user message. */
    prompt: string
    /** Optional slug to thread through the seed for context-envelope use. */
    agentSlug?: string
    /** Label override. Default: "Edit with AI". */
    label?: string
    /** Tighter sizing for use inside dense rows. Default: false. */
    compact?: boolean
    /** Optional extra classes for one-off layout tweaks. */
    className?: string
}

export function EditWithAIButton({
    prompt,
    agentSlug,
    label = 'Edit with AI',
    compact = false,
    className = '',
}: EditWithAIButtonProps): React.ReactElement {
    const { startConcierge } = useDockStore()
    const { layout, setVisible } = useDockLayout()

    const onClick = (): void => {
        // Pop the dock open if it was hidden — clicking here is an
        // explicit "I want to talk to the AI now" so an invisible dock
        // would just be confusing.
        if (!layout.visible) {
            setVisible(true)
        }
        startConcierge({ prompt, agentSlug })
    }

    const base =
        'inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-border bg-card font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-accent hover:text-foreground'
    const sizing = compact ? 'h-5 px-1.5 text-[0.625rem]' : 'h-6 px-2 text-[0.6875rem]'
    return (
        <button
            type="button"
            onClick={onClick}
            className={`${base} ${sizing} ${className}`.trim()}
            data-slot="edit-with-ai"
            title={prompt}
        >
            <SparklesIcon className={compact ? 'h-2.5 w-2.5' : 'h-3 w-3'} aria-hidden />
            {label}
        </button>
    )
}
