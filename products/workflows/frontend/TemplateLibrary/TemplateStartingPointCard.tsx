import { IconLetter } from '@posthog/icons'

import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'
import { cn } from 'lib/utils/css-classes'

import { MessageTemplate } from './types'

export interface TemplateStartingPointCardProps {
    template: MessageTemplate
    picked: boolean
    onClick: () => void
}

/** A saved template as a starting point for the AI composer: a scaled preview and the name, one pick at a time. */
export function TemplateStartingPointCard({ template, picked, onClick }: TemplateStartingPointCardProps): JSX.Element {
    const name = template.name || 'Unnamed template'
    const html = template.content?.email?.html

    return (
        <button
            type="button"
            onClick={onClick}
            aria-pressed={picked}
            title={template.description || name}
            data-attr="new-template-agent-starting-point"
            className={cn(
                'flex flex-col w-40 text-left border rounded overflow-hidden bg-surface-primary',
                'hover:border-accent focus-visible:outline-accent motion-safe:transition-colors',
                picked && 'border-accent ring-1 ring-accent'
            )}
        >
            {html ? (
                <EmailPreviewThumbnail html={html} title={`${name} preview`} size="card" className="border-b" />
            ) : (
                <span className="flex items-center justify-center w-40 h-28 border-b bg-surface-secondary text-secondary text-2xl">
                    <IconLetter />
                </span>
            )}
            <span className="px-2 py-1.5 text-xs font-semibold truncate w-full">{name}</span>
        </button>
    )
}
