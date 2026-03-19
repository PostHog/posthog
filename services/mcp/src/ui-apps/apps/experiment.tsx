import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type ExperimentData, ExperimentView } from 'products/experiments/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function ExperimentApp(): JSX.Element {
    return (
        <AppWrapper<ExperimentData> appName="PostHog Experiment">
            {({ data }) => <ExperimentView experiment={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExperimentApp />)
}
