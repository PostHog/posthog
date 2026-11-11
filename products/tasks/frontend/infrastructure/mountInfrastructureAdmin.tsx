import './infrastructureAdmin.css'

import { resetContext } from 'kea'
import { disposablesPlugin } from 'kea-disposables'
import { loadersPlugin } from 'kea-loaders'
import { createRoot } from 'react-dom/client'

import { ThemeProvider } from '@posthog/quill'

import { InfrastructureAdmin } from './InfrastructureAdmin'

resetContext({ plugins: [loadersPlugin(), disposablesPlugin] })

function mount(): void {
    const root = document.getElementById('root')
    if (root) {
        createRoot(root).render(
            <ThemeProvider defaultTheme="light">
                <InfrastructureAdmin region={root.dataset.region || 'local'} />
            </ThemeProvider>
        )
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true })
} else {
    mount()
}
