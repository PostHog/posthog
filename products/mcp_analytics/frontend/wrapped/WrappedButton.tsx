import './MCPWrapped.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'

import { colors } from '@posthog/brand/colors'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconGift } from 'lib/lemon-ui/icons'

import { mcpWrappedLogic } from './mcpWrappedLogic'

// The intro card's colors, so the button reads as the way into the story.
const GRADIENT = { '--wrapped-from': colors.violet.core, '--wrapped-to': colors.tangerine.core } as CSSProperties

function WrappedButtonContent({ quill }: { quill: boolean }): JSX.Element | null {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { openStory } = useActions(mcpWrappedLogic)
    if (!wrapped) {
        return null
    }
    const content = (
        <>
            <IconGift className="text-base" />
            Your {wrapped.year} wrapped
        </>
    )
    return quill ? (
        <Button
            variant="outline"
            className="MCPWrapped__header-button"
            style={GRADIENT}
            onClick={() => openStory('header_button')}
            data-attr="mcp-wrapped-header-button"
        >
            {content}
        </Button>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            className="MCPWrapped__header-button"
            style={GRADIENT}
            onClick={() => openStory('header_button')}
            data-attr="mcp-wrapped-header-button"
        >
            {content}
        </LemonButton>
    )
}

/** Reopens MCP Wrapped from the scene header while a wrap is fresh. Mounts nothing with the flag off. */
export function WrappedButton({ quill }: { quill: boolean }): JSX.Element | null {
    const enabled = useFeatureFlag('MCP_ANALYTICS_WRAPPED')
    return enabled ? <WrappedButtonContent quill={quill} /> : null
}
