import { registerIntegrationSetup } from 'lib/components/CyclotronJob/integrations/integrationSetupRegistry'

import { CursorSetupModal } from './CursorSetupModal'

registerIntegrationSetup({
    kind: 'cursor',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Cursor account',
        onClick: () => openModal('cursor'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <CursorSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})
