import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

export interface WorkflowTemplateCardProps {
    name: string
    description?: string | null
    /** Icons that show what the template does, drawn above the name. */
    preview: JSX.Element
    /** Short line under the description, such as how the workflow starts. */
    footer?: JSX.Element | null
    onClick: () => void
    onEdit?: (e: React.MouseEvent) => void
    onDelete?: (e: React.MouseEvent) => void
    'data-attr': string
}

export function WorkflowTemplateCard({
    name,
    description,
    preview,
    footer,
    onClick,
    onEdit,
    onDelete,
    'data-attr': dataAttr,
}: WorkflowTemplateCardProps): JSX.Element {
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    return (
        <div className="relative">
            <button
                type="button"
                onClick={onClick}
                data-attr={dataAttr}
                className="flex flex-col gap-2 w-full h-full p-3 text-left border rounded bg-surface-primary hover:border-primary hover:bg-surface-secondary transition-colors"
            >
                {preview}
                <div className="flex flex-col gap-0.5 grow">
                    <span className="font-semibold truncate">{name}</span>
                    {description && <p className="mb-0 text-xs text-secondary line-clamp-2">{description}</p>}
                </div>
                {footer}
            </button>
            {(onEdit || onDelete) && (
                <div className="absolute top-1.5 right-1.5">
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
