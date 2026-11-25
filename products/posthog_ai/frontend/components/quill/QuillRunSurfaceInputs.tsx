import { type ReactNode, useState } from 'react'

import { useElementHeight } from '../../hooks/useElementHeight'

const noop = (): void => {}

const COLUMN_CLASS = 'pointer-events-auto mx-auto w-full max-w-180 px-4'

export interface QuillRunSurfaceInputsProps {
    approval: ReactNode
    showApproval: boolean
    composer: ReactNode
    onHeightChange?: (height: number) => void
}

/**
 * The quill skin of the run surface's input region. It floats over the thread's bottom edge: messages fade
 * out in the strip above the inputs and stay hidden behind them. The fade lets clicks through to the
 * thread; only the inputs take them.
 */
export function QuillRunSurfaceInputs({
    approval,
    showApproval,
    composer,
    onHeightChange = noop,
}: QuillRunSurfaceInputsProps): JSX.Element {
    const [node, setNode] = useState<HTMLDivElement | null>(null)
    useElementHeight(node, onHeightChange)
    return (
        <div className="relative z-10 h-0 shrink-0">
            {/* `data-not-quill` keeps `--color-bg-primary` the page background, which a quill ancestor rebinds to its brand color. */}
            <div
                ref={setNode}
                data-not-quill
                className="pointer-events-none absolute inset-x-0 bottom-0 pt-6 bg-[linear-gradient(to_bottom,transparent,var(--color-bg-primary)_1.5rem)]"
            >
                {approval && (
                    <div hidden={!showApproval} className="pb-4" data-attr="run-approval">
                        <div className={COLUMN_CLASS}>{approval}</div>
                    </div>
                )}
                {composer && (
                    <div
                        hidden={showApproval}
                        data-attr="composer"
                        className="pb-[calc(1rem_+_env(safe-area-inset-bottom))]"
                    >
                        <div className={COLUMN_CLASS}>{composer}</div>
                    </div>
                )}
            </div>
        </div>
    )
}
