import '../../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type SurveyStatsData, SurveyStatsView } from 'products/surveys/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function SurveyStatsApp(): JSX.Element {
    return (
        <AppWrapper<SurveyStatsData> appName="PostHog Survey Stats">
            {({ data }) => <SurveyStatsView data={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<SurveyStatsApp />)
}
