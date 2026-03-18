import '../../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { type ActionData, ActionView } from 'products/actions/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function ActionApp(): JSX.Element {
    return <AppWrapper<ActionData> appName="PostHog Action">{({ data }) => <ActionView action={data!} />}</AppWrapper>
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ActionApp />)
}
