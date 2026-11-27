import './MCPWrapped.scss'

import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { mcpWrappedLogic } from './mcpWrappedLogic'
import { WrappedStoryPlayer } from './WrappedStoryPlayer'
import { CARD_THEMES } from './wrappedTheme'

function WrappedTeaser(): JSX.Element | null {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { openStory, closeWrapped } = useActions(mcpWrappedLogic)
    if (!wrapped) {
        return null
    }
    const Hoggie = CARD_THEMES.intro.hoggie
    return (
        <div
            className="MCPWrapped__teaser relative overflow-hidden rounded-xl p-6 pr-44 text-white"
            style={{ background: CARD_THEMES.intro.background }}
        >
            <div className="MCPWrapped__rise flex flex-col gap-2">
                <span className="font-mono text-xs font-semibold uppercase tracking-wider opacity-80">
                    MCP Wrapped · {wrapped.year}
                </span>
                <h2 className="m-0 text-2xl font-bold leading-tight">Your MCP Wrapped is ready!</h2>
                <p className="m-0 text-sm text-balance opacity-90">
                    <span className="MCPWrapped__mark">
                        {wrapped.cards.tool_calls.total_calls.toLocaleString('en-US')} tool calls
                    </span>
                    , your most-called tools, and the AI apps and models behind them. It takes about a minute.
                </p>
                <div className="mt-3 flex gap-2">
                    <Button
                        size="lg"
                        className="MCPWrapped__teaser-play"
                        onClick={() => openStory('pop_up')}
                        data-attr="mcp-wrapped-teaser-play"
                    >
                        Play
                    </Button>
                    <Button
                        size="lg"
                        className="MCPWrapped__teaser-later"
                        onClick={closeWrapped}
                        data-attr="mcp-wrapped-teaser-later"
                    >
                        Later
                    </Button>
                </div>
            </div>
            {/* Pinned to the corner at the card's full height, so it fills the space beside the text at any text length. */}
            <div className="MCPWrapped__pop absolute -bottom-3 -right-2 h-[96%]">
                <span className="absolute bottom-[15%] left-1/2 size-36 -translate-x-1/2 rounded-full bg-white/20 blur-3xl" />
                <Hoggie className="relative h-full w-auto" loading="eager" />
            </div>
        </div>
    )
}

function MCPWrappedOverlay(): JSX.Element | null {
    const { view } = useValues(mcpWrappedLogic)
    const { closeWrapped } = useActions(mcpWrappedLogic)
    if (view === 'closed') {
        return null
    }
    return (
        <LemonModal
            isOpen
            onClose={closeWrapped}
            simple
            hideCloseButton
            width={view === 'teaser' ? 540 : 400}
            className="!border-none !bg-transparent !shadow-none"
            overlayClassName="MCPWrapped__overlay"
            data-attr="mcp-wrapped"
        >
            {view === 'teaser' ? <WrappedTeaser /> : <WrappedStoryPlayer />}
        </LemonModal>
    )
}

/** The MCP Wrapped pop-up and story. Mounts nothing while the flag is off. */
export function MCPWrapped(): JSX.Element | null {
    const enabled = useFeatureFlag('MCP_ANALYTICS_WRAPPED')
    return enabled ? <MCPWrappedOverlay /> : null
}
