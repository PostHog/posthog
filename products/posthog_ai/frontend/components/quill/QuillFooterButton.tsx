import { type ReactNode, useEffect, useRef, useState } from 'react'

import { IconCheck, IconCopy } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

/**
 * Icon affordance for message and turn footers. Stays muted whether idle or active: the icon carries
 * the state, so the row never lights up in a colour the thread doesn't use elsewhere.
 */
export function QuillFooterButton({
    label,
    tooltip,
    onClick,
    dataAttr,
    children,
}: {
    label: string
    tooltip?: string
    onClick: () => void
    dataAttr?: string
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label={label}
                        onClick={onClick}
                        data-attr={dataAttr}
                        className="text-muted-foreground hover:text-foreground"
                    >
                        {children}
                    </Button>
                }
            />
            <TooltipContent>{tooltip ?? label}</TooltipContent>
        </Tooltip>
    )
}

const COPIED_MS = 2000

export function QuillCopyButton({
    value,
    label,
    dataAttr,
}: {
    value: string
    label: string
    dataAttr?: string
}): JSX.Element {
    const [copied, setCopied] = useState(false)
    const timer = useRef<ReturnType<typeof setTimeout>>()
    useEffect(() => () => clearTimeout(timer.current), [])
    return (
        <QuillFooterButton
            label={label}
            tooltip={copied ? 'Copied' : label}
            dataAttr={dataAttr}
            onClick={() => {
                void copyToClipboard(value, 'text', { silent: true })
                setCopied(true)
                clearTimeout(timer.current)
                timer.current = setTimeout(() => setCopied(false), COPIED_MS)
            }}
        >
            {copied ? <IconCheck /> : <IconCopy />}
        </QuillFooterButton>
    )
}
