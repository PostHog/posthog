// Newest first.
const REVISIONS: [string, string][] = [
    ['2026-07-28', 'Stateless. No initialize handshake and no session ID.'],
    ['2025-11-25', 'Tasks for long-running calls, URL elicitation, tool calls inside sampling, and icons.'],
    ['2025-06-18', 'Structured tool output, elicitation, and resource links. Removed JSON-RPC batching.'],
    ['2025-03-26', 'Streamable HTTP transport, OAuth 2.1 authorization, and tool annotations.'],
    ['2024-11-05', 'The first revision: tools, resources, prompts, and sampling over stdio or HTTP with SSE.'],
]

export function ProtocolVersionDescription(): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <p className="m-0">
                The MCP spec revision a client and your server agreed on when they connected. Versions marked current
                are on the stateless revision or later.
            </p>
            <ul className="m-0 flex list-none flex-col gap-1 p-0">
                {REVISIONS.map(([version, change]) => (
                    <li key={version}>
                        <span className="font-semibold" translate="no">
                            {version}
                        </span>
                        <span>: {change}</span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
