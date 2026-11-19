import { BindLogic } from 'kea'
import { ReactNode } from 'react'

import { emailDomainAgentLogic } from './emailDomainAgentLogic'
import { emailDomainAutoConfigureLogic } from './emailDomainAutoConfigureLogic'
import { emailDomainLogic } from './emailDomainLogic'
import { EmailDomainLogicProps } from './emailDomainLogicProps'
import { emailDomainManualSetupLogic } from './emailDomainManualSetupLogic'
import { emailDomainSenderLogic } from './emailDomainSenderLogic'
import { emailDomainStatusLogic } from './emailDomainStatusLogic'

const LOGICS = [
    emailDomainSenderLogic,
    emailDomainStatusLogic,
    emailDomainAutoConfigureLogic,
    emailDomainManualSetupLogic,
    emailDomainAgentLogic,
    emailDomainLogic,
]

export function BindEmailDomainLogics({
    id,
    origin,
    children,
}: EmailDomainLogicProps & { children: ReactNode }): JSX.Element {
    return LOGICS.reduceRight(
        (inner, logic) => (
            <BindLogic logic={logic} props={{ id, origin }}>
                {inner}
            </BindLogic>
        ),
        <>{children}</>
    )
}
