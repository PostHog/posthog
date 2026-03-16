import '../../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type FeatureFlagData, FeatureFlagView } from 'products/feature_flags/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function FeatureFlagApp(): JSX.Element {
    return (
        <AppWrapper<FeatureFlagData> appName="PostHog Feature Flag">
            {({ data }) => <FeatureFlagView flag={data!} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<FeatureFlagApp />)
}
