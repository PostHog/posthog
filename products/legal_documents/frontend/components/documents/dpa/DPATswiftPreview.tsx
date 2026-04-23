import { SignatureBlock } from '../../base/SignatureBlock'

const TSWIFT_IMG = 'https://res.cloudinary.com/dmukukwp6/image/upload/posthog.com/src/images/dpa/t-swift.png'

export function DPATswiftPreview(): JSX.Element {
    return (
        <div className="legal-document-preview legal-document-preview--tswift max-w-3xl mx-auto">
            <img src={TSWIFT_IMG} alt="Taylor Swift hog" className="legal-document-preview__tswift-portrait" />

            <h3>Data Dance</h3>

            <p>
                We started with a promise, data in our hands,
                <br />
                You're the controller, I'm the one who understands,
                <br />
                You wanna share your secrets, let me hold the key,
                <br />
                We'll keep it all secure, like it's meant to be.
            </p>
            <p>
                We'll follow every rule, every law, every line,
                <br />
                From the EEA to the Swiss, we'll keep it fine,
                <br />
                No breach of trust, no whispers in the dark,
                <br />
                We'll protect it all, every little spark.
            </p>
            <p className="font-bold">
                This is our data dance, under moonlit skies,
                <br />
                With the GDPR watching, we'll never compromise,
                <br />
                I'll be your processor, with a duty so true,
                <br />
                Every byte, every bit, I'll handle it for you.
            </p>
            <p>
                If there's a breach, I'll let you know,
                <br />
                In the dead of night, or the morning glow,
                <br />
                We'll fix it fast, we'll make it right,
                <br />
                Together we'll stand, in this data fight.
            </p>
            <p className="font-bold">
                This is our data dance, under moonlit skies,
                <br />
                With the GDPR watching, we'll never compromise,
                <br />
                I'll be your processor, with a duty so true,
                <br />
                Every byte, every bit, I'll handle it for you.
            </p>
            <p>
                In this digital world, where privacy's the song,
                <br />
                We'll keep on dancing, where we both belong,
                <br />
                With every step, we'll take this vow,
                <br />
                To protect and cherish, here and now.
            </p>

            <div className="clear-both pt-6">
                <SignatureBlock />
            </div>
        </div>
    )
}
