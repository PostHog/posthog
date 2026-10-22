import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { customChartModalLogic, CustomChartModalLogicProps } from './customChartModalLogic'

const SUGGESTIONS: Record<string, string[]> = {
    TrendsQuery: [
        'A calendar heatmap with one cell per day',
        'A bullet chart of each series against its previous period',
        'A waffle chart of the share of each breakdown value',
    ],
    FunnelsQuery: [
        'A Sankey diagram of who continues and who drops off at each step',
        'Horizontal bars per step, with the drop-off labeled between steps',
    ],
    RetentionQuery: [
        'One line per cohort, with older cohorts faded',
        'A triangle heatmap with the percentage in each cell',
    ],
    HogQLQuery: ['A scatter plot of the first two numeric columns', 'A treemap of the rows by their largest value'],
}
const DEFAULT_SUGGESTIONS = ['A radial bar chart of the totals', 'A small multiple chart per series']

export function CustomChartModal({ logicProps }: { logicProps: CustomChartModalLogicProps }): JSX.Element {
    const logic = customChartModalLogic(logicProps)
    const { isOpen, description, submitting, submitDisabledReason } = useValues(logic)
    const { closeModal, setDescription, submit } = useActions(logic)
    const kind = logicProps.data?.query.kind
    const suggestions = (typeof kind === 'string' && SUGGESTIONS[kind]) || DEFAULT_SUGGESTIONS

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={submitting ? undefined : closeModal}
            title="Custom chart"
            description="Describe the chart you want. An agent builds it from this insight's results, which takes a few minutes. It then replaces the built-in chart here and on dashboards."
            width={560}
            hasUnsavedInput={!!description.trim()}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={submitting ? 'Starting the agent' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submit}
                        loading={submitting}
                        disabledReason={submitDisabledReason}
                        data-attr="custom-chart-build"
                    >
                        Build chart
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonTextArea
                    value={description}
                    onChange={(value) => setDescription(value)}
                    onPressCmdEnter={submit}
                    placeholder="For example: a calendar heatmap with one cell per day, darker for higher values"
                    minRows={3}
                    maxRows={10}
                    autoFocus
                    disabled={submitting}
                    data-attr="custom-chart-description"
                />
                <div className="flex flex-wrap gap-2">
                    {suggestions.map((suggestion) => (
                        <LemonButton
                            key={suggestion}
                            size="xsmall"
                            type="secondary"
                            disabledReason={submitting ? 'Starting the agent' : undefined}
                            onClick={() => setDescription(suggestion, true)}
                            data-attr="custom-chart-suggestion"
                        >
                            {suggestion}
                        </LemonButton>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
