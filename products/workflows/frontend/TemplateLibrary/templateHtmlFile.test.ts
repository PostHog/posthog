import { TemplateHtmlFileContent, templateHtmlFile } from './templateHtmlFile'

// `sdk` is what posthog-node's `parseTemplateFile` returned for each `file`,
// recorded at PostHog/posthog-js#5312's head (87e9e95ca65).
interface SdkParse {
    subject: string
    preheader?: string
}

const SDK_UPLOADED_FILES: { name: string; file: string; sdk: SdkParse }[] = [
    {
        name: 'entities in the title and preheader, Liquid in the body',
        file: '<!doctype html><html><head><title>Welcome &amp; hello</title><meta name="preheader" content="A &quot;small&quot; preview"></head><body><p>{{ variables.first_name }}</p></body></html>\n',
        sdk: {
            subject: 'Welcome & hello',
            preheader: 'A "small" preview',
        },
    },
    {
        name: "an author's own entities, whitespace and attribute order",
        file: "<!DOCTYPE html>\n<html>\n  <head>\n    <title>\n      Caf&#233; news\n    </title>\n    <meta content='Fresh &amp; warm' name=preheader>\n  </head>\n  <body><p>{{ variables.first_name }}</p></body>\n</html>\n",
        sdk: {
            subject: 'Café news',
            preheader: 'Fresh & warm',
        },
    },
    {
        name: 'no preheader, and a commented-out title before the real one',
        file: '<html>\n<head>\n<!-- <title>Old subject</title> -->\n<title>Reset your password</title>\n</head>\n<body><a href="{{ variables.reset_url }}">Reset</a></body>\n</html>\n',
        sdk: {
            subject: 'Reset your password',
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
        },
    },
    {
        name: 'a fragment without a document',
        template: { subject: 'Welcome', preheader: '', html: '<p>Hi</p>' },
        file: '<head><title>Welcome</title></head><p>Hi</p>',
        sdk: { subject: 'Welcome' },
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
        sdk: { subject: 'Welcome' },
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
        },
    },
    {
        name: 'a blank preheader with a second preheader tag behind the first',
        template: {
            subject: 'Welcome',
            preheader: '',
            html: '<html><head><title>Welcome</title><meta name="preheader" content="Old"><meta name="preheader" content="Older"></head><body></body></html>',
        },
        file: '<html><head><title>Welcome</title></head><body></body></html>',
        sdk: { subject: 'Welcome' },
    },
    {
        name: 'Liquid holding a character reference or a closing title tag',
        template: {
            subject: '{{ variables.name | default: "A &amp; B</title>" }} news',
            preheader: "Hi {{ variables.name | default: '&quot;friend&quot;' }}",
            html: '<html><head><title>Old</title></head><body></body></html>',
        },
        file: '<html><head><title>{{ variables.name | default: "A &amp;amp; B&lt;/title>" }} news</title><meta name="preheader" content="Hi {{ variables.name | default: \'&amp;quot;friend&amp;quot;\' }}"></head><body></body></html>',
        sdk: {
            subject: '{{ variables.name | default: "A &amp; B</title>" }} news',
            preheader: "Hi {{ variables.name | default: '&quot;friend&quot;' }}",
        },
    },
    {
        name: 'a subject that matches the title once its whitespace collapses',
        template: {
            subject: '  Hello   world ',
            html: '<html><head><title>Hello world</title></head><body></body></html>',
        },
        file: '<html><head><title>Hello world</title></head><body></body></html>',
        sdk: { subject: 'Hello world' },
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
