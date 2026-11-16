import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { BindEmailDomainLogics } from './BindEmailDomainLogics'
import { emailDomainLogic } from './emailDomainLogic'
import { EmailDomainLogicProps } from './emailDomainLogicProps'
import { EmailDomainSetup } from './EmailDomainSetup'

export const scene: SceneExport<EmailDomainLogicProps> = {
    component: EmailDomainScene,
    logic: emailDomainLogic,
    paramsToProps: ({ params: { id } }): EmailDomainLogicProps => ({ id: id || 'new' }),
    productKey: ProductKey.WORKFLOWS,
}

export function EmailDomainScene({ id }: EmailDomainLogicProps): JSX.Element {
    return (
        <BindEmailDomainLogics id={id || 'new'}>
            <EmailDomainSetup />
        </BindEmailDomainLogics>
    )
}
