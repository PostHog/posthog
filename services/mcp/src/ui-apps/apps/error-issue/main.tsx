import '../../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type ErrorIssueData, ErrorIssueView } from 'products/error_tracking/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function ErrorIssueApp(): JSX.Element {
    return (
        <AppWrapper<ErrorIssueData> appName="PostHog Error Issue">
            {({ data }) => <ErrorIssueView issue={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ErrorIssueApp />)
}
