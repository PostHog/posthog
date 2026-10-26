import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]) {
        return <NotFound object="page" />
    }
    return (
        <BindEmailDomainLogics id={id || 'new'}>
            <EmailDomainSetup />
        </BindEmailDomainLogics>
    )
}
