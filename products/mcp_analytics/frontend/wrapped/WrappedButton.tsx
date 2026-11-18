import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { mcpWrappedLogic } from './mcpWrappedLogic'

function WrappedButtonContent({ quill }: { quill: boolean }): JSX.Element | null {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { openStory } = useActions(mcpWrappedLogic)
    if (!wrapped) {
        return null
    }
    const label = `Your ${wrapped.year} wrapped`
    return quill ? (
        <Button variant="outline" onClick={() => openStory('header_button')} data-attr="mcp-wrapped-header-button">
            {label}
        </Button>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => openStory('header_button')}
            data-attr="mcp-wrapped-header-button"
        >
            {label}
        </LemonButton>
    )
}

/** Reopens MCP Wrapped from the scene header while a wrap is fresh. Mounts nothing with the flag off. */
export function WrappedButton({ quill }: { quill: boolean }): JSX.Element | null {
    const enabled = useFeatureFlag('MCP_ANALYTICS_WRAPPED')
    return enabled ? <WrappedButtonContent quill={quill} /> : null
}
