import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

/** User-visible rule type label — keep in sync anywhere `RuleTypeEnumApi` is shown. */
export function ruleTypeLabel(ruleType: RuleTypeEnumApi): string {
    switch (ruleType) {
        case RuleTypeEnumApi.PathDrop:
            return 'Drop when matched'
        case RuleTypeEnumApi.SeveritySampling:
            return 'Drop by severity'
        case RuleTypeEnumApi.RateLimit:
            return 'Rate limit by service'
        default: {
            return String(ruleType)
        }
    }
}
