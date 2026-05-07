import { useValues } from 'kea'

import { FIELD_IDS } from '../../../scenes/legalDocumentsConstants'
import { legalDocumentsLogic } from '../../../scenes/legalDocumentsLogic'
import { Placeholder } from '../../base/Placeholder'
import { SignatureBlock } from '../../base/SignatureBlock'

const CLOUDINARY_BASE = 'https://res.cloudinary.com/dmukukwp6/image/upload'
const FAIRYTALE_IMG = {
    map: `${CLOUDINARY_BASE}/posthog.com/src/images/dpa/map.png`,
    sword: `${CLOUDINARY_BASE}/posthog.com/src/images/dpa/sword.png`,
    wizard: `${CLOUDINARY_BASE}/posthog.com/src/images/dpa/wizard.png`,
    gnomes: `${CLOUDINARY_BASE}/posthog.com/src/images/dpa/gnomes.png`,
    porridge: `${CLOUDINARY_BASE}/posthog.com/src/images/dpa/porridge.png`,
} as const

export function DPAFairytalePreview(): JSX.Element {
    const { legalDocument } = useValues(legalDocumentsLogic)
    const { company_name } = legalDocument
    const Company = (
        <Placeholder value={company_name} fallback="[COMPANY NAME]" focusTargetId={FIELD_IDS.company_name} />
    )

    return (
        <div className="legal-document-preview legal-document-preview--fairytale max-w-2xl mx-auto">
            <h2 className="legal-document-preview__fairytale-title">
                Weaving a Magical Pact for Data Protection: An Enchanted Alliance
            </h2>

            <img
                src={FAIRYTALE_IMG.map}
                alt="A magical map"
                className="legal-document-preview__fairytale-float-right"
            />
            <p>
                Once upon a time in the enchanted land of Data, a wise and gentle kingdom known as {Company} sought to
                ensure that all its precious treasures — bits and bytes of knowledge — were safely guarded. To do this,
                they reached out to the guardian wizards of <strong>PostHog, Inc.</strong>, a famed group known for
                their powerful data spells and secure magic vaults.
            </p>

            <img
                src={FAIRYTALE_IMG.sword}
                alt="An enchanted sword"
                className="legal-document-preview__fairytale-float-left"
            />
            <p>
                {Company} and the PostHog wizards agreed to create a magical pact called the "Data Protection
                Agreement," ensuring that all the treasures would be handled with care and respect for the laws of the
                land, including the ancient scrolls of GDPR and the mystical tomes of the EEA.
            </p>

            <img
                src={FAIRYTALE_IMG.wizard}
                alt="A guardian wizard"
                className="legal-document-preview__fairytale-float-right"
            />
            <p>
                {Company}, a noble Data Controller, entrusted its treasures to the PostHog wizards. The wizards promised
                to safeguard the treasures by using their enchanted tools and secret spells to process and analyze the
                data. They vowed never to use the treasures for evil and always to follow {Company}'s wise instructions.
            </p>

            <img
                src={FAIRYTALE_IMG.gnomes}
                alt="A troupe of apprentice gnomes"
                className="legal-document-preview__fairytale-float-left"
            />
            <p>
                In the depths of their crystal-clear agreement, they outlined the adventures the data could undertake
                and specified who could handle the data, ensuring that only the most trusted apprentice wizards or
                external guardians could assist in safeguarding it. Each apprentice was sworn to secrecy with a magical
                oath to protect {Company}'s treasures.
            </p>

            <p>
                They built a fortress of security measures, enchantments so strong that only those with the right spells
                could access the treasures. They agreed to help each other in times of trouble, like when a data gremlin
                might sneak in to create mischief.
            </p>

            <img
                src={FAIRYTALE_IMG.porridge}
                alt="A celebratory bowl of porridge"
                className="legal-document-preview__fairytale-float-right"
            />
            <p>
                {Company} and PostHog celebrated their alliance with a grand feast in the grand hall, signing their pact
                with quill and enchanted ink. They agreed that their magical contract would be overseen by the wise
                elders of the land — judges from the jurisdiction of England and Wales.
            </p>

            <p>
                As the years passed, their partnership flourished. {Company}'s treasures were kept safe and grew in
                wisdom, bringing joy and prosperity to the land. And they all lived securely and data-compliantly ever
                after.
            </p>

            <div className="clear-both pt-6">
                <SignatureBlock />
            </div>
        </div>
    )
}
