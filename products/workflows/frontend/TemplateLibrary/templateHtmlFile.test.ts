import { TemplateHtmlFileContent, templateHtmlFile } from './templateHtmlFile'

// `sdk` is what posthog-node's `parseTemplateFile` and `emailContentHash` returned for each `file`,
// recorded at PostHog/posthog-js#5312's head (87e9e95ca65).
interface SdkParse {
    subject: string
    preheader?: string
    hash: string
}

const SDK_UPLOADED_FILES: { name: string; file: string; sdk: SdkParse }[] = [
    {
        name: 'entities in the title and preheader, Liquid in the body',
        file: '<!doctype html><html><head><title>Welcome &amp; hello</title><meta name="preheader" content="A &quot;small&quot; preview"></head><body><p>{{ variables.first_name }}</p></body></html>\n',
        sdk: {
            subject: 'Welcome & hello',
            preheader: 'A "small" preview',
            hash: 'v1:b967355e2c05fefe0f974b7d9d096707c2b74b8cb5ab01741c83c50d8dc1e1a8',
        },
    },
    {
        name: "an author's own entities, whitespace and attribute order",
        file: "<!DOCTYPE html>\n<html>\n  <head>\n    <title>\n      Caf&#233; news\n    </title>\n    <meta content='Fresh &amp; warm' name=preheader>\n  </head>\n  <body><p>{{ variables.first_name }}</p></body>\n</html>\n",
        sdk: {
            subject: 'Café news',
            preheader: 'Fresh & warm',
            hash: 'v1:3a18e88d481f6d67cc0f22c2dd2702ca1f116ca2aeb3e39e5e571f6029a454db',
        },
    },
    {
        name: 'no preheader, and a commented-out title before the real one',
        file: '<html>\n<head>\n<!-- <title>Old subject</title> -->\n<title>Reset your password</title>\n</head>\n<body><a href="{{ variables.reset_url }}">Reset</a></body>\n</html>\n',
        sdk: {
            subject: 'Reset your password',
            hash: 'v1:14824d9f805cfd75d9575ef7a401d44e73d1d1838ca38a8e4836fa3616b6bf93',
        },
    },
]

const ENCODED_TEMPLATES: { name: string; template: TemplateHtmlFileContent; file: string; sdk: SdkParse }[] = [
    {
        name: 'a document without a head',
        template: {
            subject: 'Welcome',
            preheader: 'Your account is ready',
            html: '<!doctype html><html><body><p>Hi {{ variables.first_name }}</p></body></html>',
        },
        file: '<!doctype html><html><head><title>Welcome</title><meta name="preheader" content="Your account is ready"></head><body><p>Hi {{ variables.first_name }}</p></body></html>',
        sdk: {
            subject: 'Welcome',
            preheader: 'Your account is ready',
            hash: 'v1:6f41d5ce967a9d7665a7fd0d9d14b556e3e414a025dfb706c84091ae4922be86',
        },
    },
    {
        name: 'a head without a title or preheader',
        template: {
            subject: 'Welcome',
            preheader: 'Your account is ready',
            html: '<html><head><meta charset="utf-8"></head><body></body></html>',
        },
        file: '<html><head><title>Welcome</title><meta name="preheader" content="Your account is ready"><meta charset="utf-8"></head><body></body></html>',
        sdk: {
            subject: 'Welcome',
            preheader: 'Your account is ready',
            hash: 'v1:415d5456b206071cbf8d9e4efee1196f5922b5ce4ed64fd6a2b6ac562cb7b63a',
        },
    },
    {
        name: 'a fragment without a document',
        template: { subject: 'Welcome', preheader: '', html: '<p>Hi</p>' },
        file: '<head><title>Welcome</title></head><p>Hi</p>',
        sdk: { subject: 'Welcome', hash: 'v1:4c98aa3a2f818cd179fb9b1d09ce903b40e759a29e47722b91b8aa997b716ec5' },
    },
    {
        name: 'a changed subject with characters that need escaping',
        template: {
            subject: 'Tom & Jerry <3 >',
            preheader: null,
            html: '<html><head><title>Old</title></head><body></body></html>',
        },
        file: '<html><head><title>Tom &amp; Jerry &lt;3 &gt;</title></head><body></body></html>',
        sdk: {
            subject: 'Tom & Jerry <3 >',
            hash: 'v1:5aed06a7538acad4ed37f04af11fb8bbda9a41ed3ae45760dd967f6d38927753',
        },
    },
    {
        name: 'a changed preheader with characters that need escaping',
        template: {
            subject: 'Welcome',
            preheader: 'Say "hi" & more',
            html: '<html><head><title>Welcome</title><meta name="preheader" content="Old"></head><body></body></html>',
        },
        file: '<html><head><title>Welcome</title><meta name="preheader" content="Say &quot;hi&quot; &amp; more"></head><body></body></html>',
        sdk: {
            subject: 'Welcome',
            preheader: 'Say "hi" & more',
            hash: 'v1:c89e519b4a6ac84a75cfa1e5fc0ab0afa681dfe9fcddd06eb03e34a7787b7cf7',
        },
    },
    {
        name: 'a blank preheader',
        template: {
            subject: 'Welcome',
            preheader: '',
            html: '<html><head><title>Welcome</title><meta name="preheader" content="Old"></head><body></body></html>',
        },
        file: '<html><head><title>Welcome</title></head><body></body></html>',
        sdk: { subject: 'Welcome', hash: 'v1:5192cb1a6d5cf5161fe843a08f2b424c15d553d76638b2f2351fa7d4b4e84560' },
    },
    {
        name: 'Liquid with quotes and comparisons in the subject and preheader',
        template: {
            subject: '{% if variables.vip %}VIP{% endif %} offer & more',
            preheader: 'Hi {{ variables.name | default: "there" }}, it\'s ready',
            html: '<html><head><title>Offer</title></head><body>{{ variables.body }}</body></html>',
        },
        file: '<html><head><title>{% if variables.vip %}VIP{% endif %} offer &amp; more</title><meta name="preheader" content=\'Hi {{ variables.name | default: "there" }}, it&#39;s ready\'></head><body>{{ variables.body }}</body></html>',
        sdk: {
            subject: '{% if variables.vip %}VIP{% endif %} offer & more',
            preheader: 'Hi {{ variables.name | default: "there" }}, it\'s ready',
            hash: 'v1:fe9529e9446c38682e58a8a6e7c0dd89ac07bc966c121d687a406993a3ec1ff5',
        },
    },
    {
        name: 'a subject that matches the title once its whitespace collapses',
        template: {
            subject: '  Hello   world ',
            html: '<html><head><title>Hello world</title></head><body></body></html>',
        },
        file: '<html><head><title>Hello world</title></head><body></body></html>',
        sdk: { subject: 'Hello world', hash: 'v1:6102b8eb57b96c2652672c55124c24fff4785856af76c25668f8ef0dbabcafcf' },
    },
]

describe('templateHtmlFile', () => {
    it.each(SDK_UPLOADED_FILES)('gives back the file the SDK uploaded byte for byte: $name', ({ file, sdk }) => {
        expect(templateHtmlFile({ subject: sdk.subject, preheader: sdk.preheader, html: file })).toBe(file)
    })

    it.each(ENCODED_TEMPLATES)('writes a file the SDK reads back as the template: $name', ({ template, file, sdk }) => {
        const encoded = templateHtmlFile(template)

        expect(encoded).toBe(file)
        expect(sdk.subject).toBe(template.subject.replace(/[\t\n\f\r ]+/g, ' ').trim())
        expect(sdk.preheader).toBe(template.preheader?.trim() ? template.preheader : undefined)
        expect(templateHtmlFile({ ...template, html: encoded })).toBe(encoded)
    })
})
