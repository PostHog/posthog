import { Card, ScrollArea, cn } from '@posthog/quill-primitives'

import { CodeLine, type Language } from 'lib/components/CodeSnippet'

import { quillCardBorderClass } from './quillCardBorder'
import { QuillCopyButton } from './QuillFooterButton'

export function QuillCodeBlock({ code, language }: { code: string; language: Language }): JSX.Element {
    return (
        <Card flush className={cn('py-0', quillCardBorderClass())}>
            {/* The scroll runs to the card edges and shadows the cut side; the padding scrolls with the code. */}
            <ScrollArea viewportClassName="py-2.5 pe-10 ps-3" data-not-quill>
                <div className="w-max font-mono text-xs">
                    <CodeLine text={code} language={language} wrapLines={false} />
                </div>
            </ScrollArea>
            <div className="absolute end-1.5 top-1.5 z-20">
                <QuillCopyButton value={code} label="Copy code" />
            </div>
        </Card>
    )
}

/** `LemonMarkdown`'s `renderCodeBlock` for the quill thread. Module-level, so markdown blocks stay memoized. */
export function renderQuillCodeBlock(code: string, language: Language): JSX.Element {
    return <QuillCodeBlock code={code} language={language} />
}
