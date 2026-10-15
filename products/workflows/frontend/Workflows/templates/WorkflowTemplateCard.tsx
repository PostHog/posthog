import clsx from 'clsx'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

export interface WorkflowTemplateCardProps {
    name: string
    description?: string | null
    /** Icons that show what the template does, drawn above the name. */
    preview: JSX.Element
    /** Marker next to the name, such as the AI badge. */
    badge?: JSX.Element | null
    /** Short line under the description, such as how the workflow starts. */
    footer?: JSX.Element | null
    onClick: () => void
    onEdit?: (e: React.MouseEvent) => void
    onDelete?: (e: React.MouseEvent) => void
    /** Marks the card as the current choice, for pickers that select a template before they create anything. */
    selected?: boolean
    'data-attr': string
}

export function WorkflowTemplateCard({
    name,
    description,
    preview,
    badge,
    footer,
    onClick,
    onEdit,
    onDelete,
    selected,
    'data-attr': dataAttr,
}: WorkflowTemplateCardProps): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const hasMenu = !!onEdit || !!onDelete

    return (
        <div className="relative">
            <button
                type="button"
                onClick={onClick}
                data-attr={dataAttr}
                aria-pressed={selected}
                className={clsx(
                    'flex flex-col gap-2 w-full h-full p-4 text-left border rounded bg-surface-primary hover:border-primary hover:bg-surface-secondary transition-colors',
                    selected && 'border-accent ring-1 ring-accent'
                )}
            >
                {preview}
                <div className="flex flex-col gap-1 grow">
                    <div className={clsx('flex items-start gap-2', hasMenu && 'pr-6')}>
                        <span className="font-semibold">{name}</span>
                        {badge}
                    </div>
                    {/* Descriptions are authored with paragraphs and lists, so keep the line breaks */}
                    {description && <p className="mb-0 text-sm text-secondary whitespace-pre-line">{description}</p>}
                </div>
                {footer}
            </button>
            {hasMenu && (
                <div className="absolute top-2.5 right-2.5">
                    <More
                        size="xsmall"
                        dropdown={{
                            visible: isMenuOpen,
                            onVisibilityChange: setIsMenuOpen,
                            closeOnClickInside: true,
                        }}
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    ...(onEdit
                                        ? [
                                              {
                                                  label: 'Edit',
                                                  icon: <IconPencil />,
                                                  onClick: (e: any) => {
                                                      setIsMenuOpen(false)
                                                      onEdit(e)
                                                  },
                                              },
                                          ]
                                        : []),
                                    ...(onDelete
                                        ? [
                                              {
                                                  label: 'Delete',
                                                  status: 'danger' as const,
                                                  icon: <IconTrash />,
                                                  onClick: (e: any) => {
                                                      setIsMenuOpen(false)
                                                      onDelete(e)
                                                  },
                                              },
                                          ]
                                        : []),
                                ]}
                            />
                        }
                    />
                </div>
            )}
        </div>
    )
}
