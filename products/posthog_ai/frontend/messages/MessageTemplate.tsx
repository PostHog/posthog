import React from 'react'
import { twMerge } from 'tailwind-merge'

export interface MessageTemplateProps {
    type: 'human' | 'ai'
    variant?: 'default' | 'outline' | 'ghost'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    wrapperClassName?: string
    children?: React.ReactNode
    header?: React.ReactNode
}

export const MessageTemplate = React.forwardRef<HTMLDivElement, MessageTemplateProps>(function MessageTemplate(
    {
        type,
        variant = type === 'human' ? 'default' : 'outline',
        children,
        className,
        boxClassName,
        wrapperClassName,
        action,
        header,
    },
    ref
) {
    return (
        <div
            className={twMerge(
                'flex flex-col gap-px w-full break-words scroll-mt-12',
                type === 'human' ? 'items-end' : 'items-start',
                className
            )}
            ref={ref}
            data-message-type={type}
        >
            <div className={twMerge('min-w-0 max-w-full', wrapperClassName)}>
                {header}
                {children && (
                    <div
                        className={twMerge(
                            'border py-2 px-3 rounded-lg',
                            variant === 'default' && 'border-transparent bg-surface-secondary',
                            variant === 'outline' && 'bg-surface-primary',
                            variant === 'ghost' && 'border-transparent bg-transparent',
                            boxClassName
                        )}
                    >
                        {children}
                    </div>
                )}
            </div>
            {action}
        </div>
    )
})
