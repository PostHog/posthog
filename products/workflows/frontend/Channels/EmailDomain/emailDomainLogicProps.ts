import { EmailDomainSetupOrigin } from './emailDomainSetupOrigin'

export interface EmailDomainLogicProps {
    /** The integration id, or `new` for the domain step. */
    id: string
    /** Where the setup returns the person. Defaults to workflows. */
    origin?: EmailDomainSetupOrigin
}

export const integrationIdOf = (id: string): number | null => (/^\d+$/.test(id) ? Number(id) : null)
