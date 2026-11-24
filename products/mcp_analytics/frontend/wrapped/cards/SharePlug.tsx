import { IconLogomark } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

const MCP_ANALYTICS_URL = 'https://posthog.com/mcp-analytics'

/** The foot of the share card, telling anyone who sees the picture where to get one for their own server. */
export function SharePlug(): JSX.Element {
    return (
        <LinkPrimitive
            to={MCP_ANALYTICS_URL}
            target="_blank"
            className="MCPWrapped__rise mt-auto flex items-center justify-center gap-2.5 border-t-2 border-dashed border-white/15 pt-3 text-current no-underline"
            data-attr="mcp-wrapped-share-plug"
        >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-black">
                <IconLogomark className="size-5" />
            </span>
            <span className="text-xs leading-tight">
                <span className="block font-bold">Which personality is your MCP server?</span>
                <span className="opacity-75">Find out at posthog.com/mcp-analytics</span>
            </span>
        </LinkPrimitive>
    )
}
