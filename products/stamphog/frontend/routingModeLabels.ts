import { RoutingModeEnumApi } from './generated/api.schemas'

// The repo settings and the activity log both name when reviewer requests run, so they read from one map.
export const ROUTING_MODE_LABELS: Record<RoutingModeEnumApi, string> = {
    [RoutingModeEnumApi.Off]: 'Off',
    [RoutingModeEnumApi.Fallback]: "When Stamphog doesn't approve",
    [RoutingModeEnumApi.Always]: 'On every pull request',
}
