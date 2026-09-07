import { BindLogic, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { GatewayRouteGuardLogicProps, gatewayRouteGuardLogic } from './gatewayRouteGuardLogic'

export function GatewayRouteGuard({
    children,
    requiresAdmin = false,
}: {
    children: React.ReactNode
    requiresAdmin?: boolean
}): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)

    if (!currentTeamId) {
        return null
    }

    const logicProps: GatewayRouteGuardLogicProps = { projectId: currentTeamId, requiresAdmin }

    return (
        <BindLogic logic={gatewayRouteGuardLogic} props={logicProps}>
            <GatewayRouteGuardContent {...logicProps}>{children}</GatewayRouteGuardContent>
        </BindLogic>
    )
}

function GatewayRouteGuardContent({
    children,
    ...logicProps
}: GatewayRouteGuardLogicProps & { children: React.ReactNode }): JSX.Element | null {
    const { canRender } = useValues(gatewayRouteGuardLogic(logicProps))

    return canRender ? <>{children}</> : null
}
