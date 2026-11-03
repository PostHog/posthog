import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { AppWrapper } from '../components/AppWrapper'
import { ExplainChart, type ExplainChartData } from '../components/ExplainChart'

function ExplainChartApp(): JSX.Element {
    return (
        <AppWrapper<ExplainChartData> appName="PostHog Chart Explanation">
            {({ data, openLink, app }) => <ExplainChart data={data!} openLink={openLink} app={app} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExplainChartApp />)
}
