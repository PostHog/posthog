import { LogsExclusionRuleRuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

/** User-visible rule type label — keep in sync anywhere `LogsExclusionRuleRuleTypeEnumApi` is shown. */
export function ruleTypeLabel(ruleType: LogsExclusionRuleRuleTypeEnumApi): string {
    switch (ruleType) {
        case LogsExclusionRuleRuleTypeEnumApi.PathDrop:
            return 'Drop'
        case LogsExclusionRuleRuleTypeEnumApi.SeveritySampling:
            return 'Drop by severity'
        case LogsExclusionRuleRuleTypeEnumApi.RateLimit:
            return 'Rate limit'
        default: {
            return String(ruleType)
        }
    }
}
