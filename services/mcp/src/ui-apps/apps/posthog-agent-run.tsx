import '../styles/tailwind.css'

import { createRoot } from 'react-dom/client'

import { AgentOperationApp } from '../components/AgentOperationApp'

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<AgentOperationApp />)
}
