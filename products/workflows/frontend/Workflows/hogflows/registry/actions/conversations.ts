import { SUPPORT_TICKET_NODES } from 'products/workflows/frontend/Workflows/hogflows/builtInSteps'
import { registerActionNodeCategory } from 'products/workflows/frontend/Workflows/hogflows/registry/actions/actionNodeRegistry'

registerActionNodeCategory({ label: 'Support', nodes: SUPPORT_TICKET_NODES })
