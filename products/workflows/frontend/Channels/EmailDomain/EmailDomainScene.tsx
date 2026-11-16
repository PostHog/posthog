import { useValues } from 'kea'
import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { BindEmailDomainLogics } from './BindEmailDomainLogics'
import { emailDomainLogic } from './emailDomainLogic'
import { EmailDomainLogicProps } from './emailDomainLogicProps'
import { EmailDomainSetup } from './EmailDomainSetup'
import { originFromSearchParams } from './emailDomainSetupOrigin'

export const scene: SceneExport<EmailDomainLogicProps> = {
    component: EmailDomainScene,
    logic: emailDomainLogic,
    paramsToProps: ({ params: { id }, searchParams }): EmailDomainLogicProps => ({
        id: id || 'new',
        origin: originFromSearchParams(searchParams),
    }),
    productKey: ProductKey.WORKFLOWS,
}

export function EmailDomainScene({ id }: Pick<EmailDomainLogicProps, 'id'>): JSX.Element {
    const { searchParams } = useValues(router)
    return (
        <BindEmailDomainLogics id={id || 'new'} origin={originFromSearchParams(searchParams)}>
            <EmailDomainSetup />
        </BindEmailDomainLogics>
    )
}
