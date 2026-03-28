import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type ErrorDetailsData, ErrorDetailsView } from 'products/error_tracking/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function ErrorDetailsApp(): JSX.Element {
    return (
        <AppWrapper<ErrorDetailsData> appName="PostHog Error Details">
            {({ data }) => <ErrorDetailsView data={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ErrorDetailsApp />)
}
