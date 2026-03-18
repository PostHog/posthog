import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type CohortData, CohortView } from 'products/cohorts/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function CohortApp(): JSX.Element {
    return <AppWrapper<CohortData> appName="PostHog Cohort">{({ data }) => <CohortView cohort={data!} />}</AppWrapper>
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<CohortApp />)
}
