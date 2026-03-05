import '../../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type ExperimentResultsData, ExperimentResultsView } from 'products/experiments/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function ExperimentResultsApp(): JSX.Element {
    return (
        <AppWrapper<ExperimentResultsData> appName="PostHog Experiment Results">
            {({ data }) => <ExperimentResultsView data={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExperimentResultsApp />)
}
