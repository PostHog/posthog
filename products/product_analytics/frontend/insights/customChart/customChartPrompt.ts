import { CustomChartData, sampleCustomChartData } from './customChartData'

export function buildCustomChartInstruction({
    description,
    insightName,
    data,
}: {
    description: string
    insightName: string
    data: CustomChartData
}): string {
    const kind = typeof data.query.kind === 'string' ? data.query.kind : 'query'
    return `${description.trim()}

Build this as the custom chart for the PostHog insight "${insightName}". It replaces the insight's built-in chart on the insight page and on dashboards.

Data:
- Subscribe with \`ph.onInsightData(listener, { sample: SAMPLE })\` from \`@posthog/canvas-sdk\`, and redraw with every value the listener receives. Read "Insight charts" in the \`querying-canvas-data\` skill.
- Put the sample below in the source as \`SAMPLE\`. The canvas scene draws the sample. The insight sends its live data instead.
- The data is \`{ query, results, columns?, types? }\`. \`query\` is the insight's ${kind} source query, and \`results\` is its results. The sample has the same shape, with fewer series, rows and points.
- Do not call \`ph.loadInsight\` or \`ph.query\`, and declare no data capabilities.

Look:
- Draw with \`@posthog/quill-charts\`. When it does not ship this chart, follow the \`drawing-custom-charts\` skill.
- Fill the whole frame. Add no page header, title or outer padding, because the insight shows its own title.
- Support the light and dark themes. Show a short empty state when \`results\` is empty.

Sample:
\`\`\`json
${JSON.stringify(sampleCustomChartData(data), null, 2)}
\`\`\``
}
