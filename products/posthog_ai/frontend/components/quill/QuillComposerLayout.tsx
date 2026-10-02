import type { ReactNode, RefObject } from 'react'

import { InputGroup, InputGroupAddon } from '@posthog/quill-primitives'

export interface QuillComposerLayoutProps {
    groupRef: RefObject<HTMLDivElement>
    textAreaRef: RefObject<HTMLTextAreaElement>
    chips: ReactNode
    field: ReactNode
    send: ReactNode
    controls: ReactNode
    meta: ReactNode
}

export function QuillComposerLayout({
    groupRef,
    textAreaRef,
    chips,
    field,
    send,
    controls,
    meta,
}: QuillComposerLayoutProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <InputGroup
                ref={groupRef}
                onClick={(event) => {
                    if (!(event.target as HTMLElement).closest('button, a, input, textarea, [role="menu"]')) {
                        textAreaRef.current?.focus()
                    }
                }}
                className={
                    // The textarea is Lemon's, so quill's own focus rule, keyed to its input slot, never fires here.
                    'h-auto cursor-text bg-[var(--card)] focus-within:border-[color-mix(in_oklab,var(--ring)_50%,transparent)] focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_30%,transparent)] ' +
                    // LemonTextArea puts the composer's padding on both its wrapper and the textarea. The wrapper keeps it, so the textarea drops it. The textarea keeps 2px on the left because it clips the caret at x=0.
                    '[&_[data-slot=composer-placeholder]]:top-2 [&_[data-slot=composer-placeholder]]:left-2.5 [&_textarea]:min-h-[37px] [&_textarea]:p-0 [&_textarea]:pl-0.5'
                }
            >
                <InputGroupAddon align="block-start" className="flex-wrap">
                    {chips}
                </InputGroupAddon>
                <div className="relative w-full">
                    {field}
                    <span className="absolute right-1 bottom-1 flex items-center">{send}</span>
                </div>
            </InputGroup>
            <div
                data-quill
                className="@container/composer flex flex-wrap items-center gap-1 px-1 text-[var(--foreground)]"
            >
                {controls}
                <div className="ml-auto">{meta}</div>
            </div>
        </div>
    )
}
