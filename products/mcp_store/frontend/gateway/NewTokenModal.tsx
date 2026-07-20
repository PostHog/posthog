import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'

import { mcpGatewayLogic } from './mcpGatewayLogic'

/** Shows a freshly-issued gateway token exactly once (creation or rotation). */
export function NewTokenModal(): JSX.Element {
    const { newlyIssuedToken } = useValues(mcpGatewayLogic)
    const { dismissNewToken } = useActions(mcpGatewayLogic)

    return (
        <LemonModal
            isOpen={!!newlyIssuedToken}
            onClose={dismissNewToken}
            title={`Gateway token for ${newlyIssuedToken?.name ?? 'agent'}`}
            footer={
                <LemonButton type="primary" onClick={dismissNewToken}>
                    Done
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-3 max-w-md">
                <LemonBanner type="warning">
                    Copy this token now — it's shown only once. The agent authenticates with it as a bearer token.
                </LemonBanner>
                {newlyIssuedToken?.token && <CodeSnippet thing="gateway token">{newlyIssuedToken.token}</CodeSnippet>}
            </div>
        </LemonModal>
    )
}
