import { cleanPastedHtml } from './cleanPastedHtml'

describe('cleanPastedHtml', () => {
    it.each([
        {
            name: 'Word list paragraphs become real, nested lists',
            input: `<p class="MsoListParagraph" style="mso-list:l0 level1 lfo1"><span style="mso-list:Ignore">·<span>&nbsp;</span></span>One</p><p class="MsoListParagraph" style="mso-list:l0 level2 lfo1"><span style="mso-list:Ignore">o</span>Two</p><p class="MsoListParagraph" style="mso-list:l0 level1 lfo1"><span style="mso-list:Ignore">·</span>Three</p>`,
            expected: '<ul><li>One<ul><li>Two</li></ul></li><li>Three</li></ul>',
        },
        {
            name: 'a second Word list starts its own list, in its own style',
            input: `<p style="mso-list:l0 level1"><span style="mso-list:Ignore">·</span>Bullet</p><p style="mso-list:l1 level1"><span style="mso-list:Ignore">1.</span>Numbered</p>`,
            expected: '<ul><li>Bullet</li></ul><ol><li>Numbered</li></ol>',
        },
        {
            name: "Word's title, comments, blank lines and fonts go",
            input: `<!--[if gte mso 9]><xml>x</xml><![endif]--><p class="MsoTitle">Plan</p><p class="MsoNormal"><b><span style="color:red;font-family:Calibri">Bold</span></b> text<o:p></o:p></p><p class="MsoNormal"><o:p>&nbsp;</o:p></p>`,
            expected: '<h1>Plan</h1><p><b>Bold</b> text</p>',
        },
        {
            name: "Google Docs' wrapper goes and its styled spans become formatting",
            input: `<b style="font-weight:normal" id="docs-internal-guid-1"><p dir="ltr"><span style="font-weight:700">Bold</span><span style="font-weight:400"> and </span><span style="font-style:italic">italic</span></p><br /><ul><li><p>Item</p></li></ul></b>`,
            expected: '<p><strong>Bold</strong> and <em>italic</em></p><ul><li><p>Item</p></li></ul>',
        },
        {
            name: "a web page's scripts, handlers and layout tables go",
            input: `<div class="x" style="color:red"><h5>Small</h5><script>alert(1)</script><a href="https://example.com" onclick="x()">Link</a><table><tr><td>A</td><td>B</td></tr></table></div>`,
            expected: '<div><h3>Small</h3><a href="https://example.com">Link</a><p>A</p><p>B</p></div>',
        },
        {
            name: "another ProseMirror app's paste is cleaned like any other page",
            input: `<p data-pm-slice="1 1 []" style="color:red;font-family:Comic Sans MS">Theirs</p>`,
            expected: '<p>Theirs</p>',
        },
    ])('$name', ({ input, expected }) => {
        expect(cleanPastedHtml(input).html).toEqual(expected)
    })

    it('counts the images it has to drop and keeps hosted ones', () => {
        const { html, droppedImages } = cleanPastedHtml(
            '<img src="file:///C:/a.png"><img src="data:image/png;base64,AAAA"><img src="https://example.com/a.png" alt="A" class="x">'
        )

        expect(droppedImages).toEqual(2)
        expect(html).toEqual('<img src="https://example.com/a.png" alt="A">')
    })

    it('keeps block styles when the paste came from this editor', () => {
        const own = '<p data-pm-slice="1 1 []" data-email-style="{&quot;color&quot;:&quot;#f00&quot;}">Mine</p>'

        expect(cleanPastedHtml(own).html).toEqual(own)
    })
})
