import METRIC_CHANGE_EXAMPLE_EMPTY from '@/templates/sections/metric-change-example-empty.md'
import METRIC_CHANGE_EXAMPLE from '@/templates/sections/metric-change-example.md'
import METRIC_EXAMPLE_CLI_CLAUDE from '@/templates/sections/metric-example-cli-claude.md'
import METRIC_EXAMPLE_CLI_EMPTY from '@/templates/sections/metric-example-cli-empty.md'
import METRIC_EXAMPLE_CLI from '@/templates/sections/metric-example-cli.md'
import METRIC_ROUTING_EMPTY from '@/templates/sections/metric-routing-empty.md'
import METRIC_ROUTING from '@/templates/sections/metric-routing.md'
import type { MetricCatalogContent } from '@/tools/types'

export type MetricCatalogMode = 'lookup' | 'empty'

export function resolveMetricCatalogMode(content: MetricCatalogContent | undefined): MetricCatalogMode {
    return content?.count === 0 ? 'empty' : 'lookup'
}

export function metricCatalogPromptVars(mode: MetricCatalogMode): Record<string, string> {
    if (mode === 'empty') {
        return {
            metric_routing: METRIC_ROUTING_EMPTY.trim(),
            metric_example_steps: METRIC_EXAMPLE_CLI_EMPTY.trim(),
            metric_example_steps_claude: METRIC_EXAMPLE_CLI_EMPTY.trim(),
            metric_change_example: METRIC_CHANGE_EXAMPLE_EMPTY.trim(),
        }
    }
    return {
        metric_routing: METRIC_ROUTING.trim(),
        metric_example_steps: METRIC_EXAMPLE_CLI.trim(),
        metric_example_steps_claude: METRIC_EXAMPLE_CLI_CLAUDE.trim(),
        metric_change_example: METRIC_CHANGE_EXAMPLE.trim(),
    }
}
