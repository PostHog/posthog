export interface EmailDomainLogicProps {
    /** The integration id, or `new` for the domain step. */
    id: string
}

export const integrationIdOf = (id: string): number | null => (/^\d+$/.test(id) ? Number(id) : null)
