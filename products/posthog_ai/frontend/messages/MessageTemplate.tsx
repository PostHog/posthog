import React from 'react'
import { twMerge } from 'tailwind-merge'

export interface MessageTemplateProps {
    type: 'human' | 'ai'
    action?: React.ReactNode
    className?: string
    boxClassName?: string
    wrapperClassName?: string
    children?: React.ReactNode
    header?: React.ReactNode
}

export const MessageTemplate = React.forwardRef<HTMLDivElement, MessageTemplateProps>(function MessageTemplate(
    { type, children, className, boxClassName, wrapperClassName, action, header },
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
            <div className={twMerge('min-w-0 max-w-full', type === 'human' && 'max-w-4/5', wrapperClassName)}>
                {header}
                {children && (
                    <div
                        className={twMerge(
                            'border py-2 px-3 rounded-lg',
                            type === 'human' ? 'border-transparent bg-surface-secondary' : 'bg-surface-primary',
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
