import { ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export interface QuillHintedTextProps {
    label: string
    hint: ReactNode
    hintText: string
    dataAttr?: string
}

export function QuillHintedText({ label, hint, hintText, dataAttr }: QuillHintedTextProps): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        tabIndex={0}
                        className="cursor-help underline decoration-dotted underline-offset-2"
                        data-attr={dataAttr}
                    />
                }
            >
                <span translate="no">{label}</span>
                <span className="sr-only">{hintText}</span>
            </TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
    )
}
