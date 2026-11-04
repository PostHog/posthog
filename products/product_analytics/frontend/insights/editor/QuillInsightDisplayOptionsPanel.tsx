import { ChartOptionSections } from 'lib/components/ChartOptions/ChartOptionSections'
import { displayOptionPages } from 'lib/components/ChartOptions/displayOptionPages'
import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { QuillChartOptionPages } from 'lib/components/ChartOptions/QuillChartOptionPages'

export function QuillInsightDisplayOptionsPanel({ tabs }: { tabs: DisplayOptionTab[] }): JSX.Element {
    const { home, pages } = displayOptionPages(tabs)

    return (
        <QuillChartOptionPages
            className="w-60 p-2"
            data-attr="insight-display-options-panel"
            home={home.length > 0 ? <ChartOptionSections sections={home} /> : null}
            pages={pages.map((page) => ({
                key: page.key,
                title: page.title,
                count: page.count,
                content: <ChartOptionSections sections={page.sections} />,
            }))}
        />
    )
}
