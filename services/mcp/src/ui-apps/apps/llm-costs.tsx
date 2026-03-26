import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type LLMCostsData, LLMCostsView } from 'products/llm_analytics/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function LLMCostsApp(): JSX.Element {
    return (
        <AppWrapper<LLMCostsData> appName="PostHog LLM Costs">{({ data }) => <LLMCostsView data={data!} />}</AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<LLMCostsApp />)
}
