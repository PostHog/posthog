import './MCPWrapped.scss'

import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

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
            className="MCPWrapped__teaser relative grid grid-cols-[1fr_7rem] gap-3 overflow-hidden rounded-xl p-5 text-white"
            style={{ background: CARD_THEMES.intro.background }}
        >
            <div className="flex flex-col gap-2">
                <span className="font-mono text-xs font-semibold uppercase tracking-wider opacity-80">
                    MCP Wrapped · {wrapped.year}
                </span>
                <h2 className="m-0 text-2xl font-bold leading-tight">Your year on MCP is ready</h2>
                <p className="m-0 text-sm opacity-90">
                    {wrapped.cards.tool_calls.total_calls.toLocaleString('en-US')} tool calls, your busiest tools, and
                    the apps and models behind them. It takes about a minute.
                </p>
            </div>
            <Hoggie className="w-28 self-end" loading="eager" />
            <div className="col-span-2 flex gap-2">
                <LemonButton type="primary" onClick={() => openStory('pop_up')} data-attr="mcp-wrapped-teaser-play">
                    Play
                </LemonButton>
                <LemonButton type="secondary" onClick={closeWrapped} data-attr="mcp-wrapped-teaser-later">
                    Later
                </LemonButton>
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
            width={view === 'teaser' ? 460 : 400}
            className="!border-none !bg-transparent !shadow-none"
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
