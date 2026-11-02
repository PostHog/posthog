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

/** Binds every logic of the sending domain page to one integration id, so the steps below can use them without props. */
export function BindEmailDomainLogics({ id, children }: EmailDomainLogicProps & { children: ReactNode }): JSX.Element {
    return LOGICS.reduceRight(
        (inner, logic) => (
            <BindLogic logic={logic} props={{ id }}>
                {inner}
            </BindLogic>
        ),
        <>{children}</>
    )
}
