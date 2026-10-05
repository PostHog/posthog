import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { AppWrapper } from '../components/AppWrapper'
import { TrackedComponent } from '../components/TrackedComponent'

function QueryResultsApp(): JSX.Element {
    return <AppWrapper appName="PostHog Query Results">{({ data }) => <TrackedComponent data={data} />}</AppWrapper>
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<QueryResultsApp />)
}
