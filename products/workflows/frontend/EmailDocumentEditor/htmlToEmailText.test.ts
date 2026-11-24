import { LiquidRenderer } from 'lib/utils/liquid'

import { htmlToEmailText, isTextOfHtml } from './htmlToEmailText'

const UNSUBSCRIBE = '{{ unsubscribe_url }}'

describe('htmlToEmailText', () => {
    it.each([
        [
            'a link',
            '<p>See <a href="https://example.com/a?x=1&amp;y=2">the news</a>.</p>',
            'See the news (https://example.com/a?x=1&y=2).',
        ],
        ['an unsubscribe link', `<a href='${UNSUBSCRIBE}'>Unsubscribe</a>`, `Unsubscribe (${UNSUBSCRIBE})`],
        [
            'a Liquid address with quotes inside',
            '<a href="{{ url | default: "https://example.com/>" }}">Go</a>',
            'Go ({{ url | default: "https://example.com/>" }})',
        ],
        ['an unquoted address', '<a href=https://example.com/a>Go</a>', 'Go (https://example.com/a)'],
        [
            'a link around an image',
            '<a href="https://example.com"><img alt="Shop" src="x"></a>',
            'Shop (https://example.com)',
        ],
        [
            'icon links next to each other',
            '<a href="https://example.com/a"><img src="x"></a><a href="https://example.com/b"><img src="y"></a>Text',
            'https://example.com/a https://example.com/b Text',
        ],
        ['a link with no text', '<a href="https://example.com"><img src="x"></a>', 'https://example.com'],
        [
            'a link whose text is its address',
            '<a href="https://example.com">https://example.com</a>',
            'https://example.com',
        ],
        ['an email address', '<a href="mailto:a@example.com">a@example.com</a>', 'a@example.com'],
        ['a link that never closes', '<p><a href="https://example.com">Go', 'Go (https://example.com)'],
        ['an image map', '<area href="https://example.com/b" alt="Part">', 'Part (https://example.com/b)'],
        ['a link to the page itself', '<a href="#top">Top</a>', 'Top'],
        ['a script address', '<a href="javascript:alert(1)">Go</a>', 'Go'],
        [
            'an Outlook copy of a button',
            '<!--[if mso]><a href="https://example.com">Go</a><![endif]--><!--[if !mso]><!--><a href="https://example.com">Go</a><!--<![endif]-->',
            'Go (https://example.com)',
        ],
        [
            'a value an import escaped for a quoted link',
            '<a href="{{ url | join: &quot;,&quot; | escape | replace: &quot;=&quot;, &quot;&amp;#x3D;&quot; | replace: &quot;`&quot;, &quot;&amp;#x60;&quot; | raw -}}">Go</a>',
            'Go ({{ url | join: &quot;,&quot; -}})',
        ],
        [
            'a value escaped for html',
            '<a href="{{ url | escape | raw }}">{{ name | escape }}</a>',
            '{{ name }} ({{ url }})',
        ],
        ['text next to a block', 'One<p>Two<div>Three</div>', 'One\nTwo\nThree'],
        ['an empty line', 'Hi,<br>\n<br>\nBye<br>Ada', 'Hi,\n\nBye\nAda'],
        ['a comparison that is not a tag', '1 < 2 & 3 &gt; 2', '1 < 2 & 3 > 2'],
        ['styles and titles', '<head><title>T</title><style>a{}</style></head><p>Body</p>', 'Body'],
    ])('writes %s', (_name, html, expected) => {
        expect(htmlToEmailText(html)).toEqual(expected)
    })

    it('keeps every filter of a long chain that another filter follows', () => {
        const chain = '|replace:"=","&#x3D;"|replace:&quot;`&quot;,&quot;&#x60;&quot;'.repeat(40_000)

        const text = htmlToEmailText(`<p>{{ x ${chain}|upcase }}</p>`)

        expect(text.match(/replace/g)).toHaveLength(80_000)
        expect(text).toMatch(/upcase }}$/)
    })

    // Liquid fails a whole send over one bad tag, so each of these has to render wherever its html does.
    it.each([
        [
            'a raw block between table rows',
            '<table>{% raw %}{{#if vip}}{% endraw %}<tr><td>VIP</td></tr>{% raw %}{{/if}}{% endraw %}</table>',
            '{{#if vip}}\nVIP\n{{/if}}',
        ],
        ['a raw block around markup', '{% raw %}<a href="{{#x}}">Go</a>{% endraw %}', 'Go ({{#x}})'],
        [
            'a raw block in an address',
            '<a href="https://example.com/{% raw %}{{#x}}{% endraw %}">Go</a>',
            'Go (https://example.com/{{#x}})',
        ],
        ['braces written as entities', '<p>&#123;&#123;#if x&#125;&#125;</p>', '{{#if x}}'],
        ['braces split over elements', '<b>{</b><i>{#if</i>', '{{#if'],
        ['a brace before a variable', '<b>{</b>{{ name }}', '{ Ada'],
        [
            'a condition that starts in an Outlook comment',
            '<!--[if mso]>{% if vip %}x<![endif]--><p>VIP</p><!--{% endif %}-->',
            'VIP',
        ],
        [
            'a condition inside an Outlook comment',
            '<!--[if mso]>{% if vip %}<td>x</td>{% endif %}<![endif]--><p>Hi</p>',
            'Hi',
        ],
        [
            'a variable set in the head',
            '<head><style>{% assign shop = "Fernhill" %}</style></head><p>{{ shop }}</p>',
            'Fernhill',
        ],
        [
            'a variable captured in the head',
            '<style>{% capture shop %}Fernhill{% endcapture %}</style>{{ shop }}',
            'Fernhill',
        ],
        [
            'a variable set in an attribute',
            `<p style="{% assign u = 'https://example.com' %}"><a href="{{ u }}">Go</a></p>`,
            'Go (https://example.com)',
        ],
        [
            'a condition around part of a tag',
            '{% if vip %}<tr class="a"{% else %}<tr class="b"{% endif %}><td>Hi</td></tr>',
            'Hi',
        ],
        ['a condition right after a tag name', '<tr{% if n > 1 %} class="x"{% endif %}><td>Hi</td></tr>', 'Hi'],
        [
            'an address that depends on a condition',
            '<a {% if vip %}href="https://example.com/vip"{% else %}href="https://example.com/all"{% endif %}>Go</a>',
            'Go (https://example.com/vip)',
        ],
        [
            'a link in a branch that starts before its tag',
            '{% if vip %}<a href="https://example.com/vip"{% else %}<a href="https://example.com/all"{% endif %}>Go</a>',
            'https://example.com/vip Go',
        ],
        [
            'an address in a branch that ends after its tag',
            '<a href="https://example.com/{% if vip %}a">V{% else %}b">N{% endif %}</a>',
            'https://example.com/a V',
        ],
        [
            'a condition that starts in an alt text',
            '<p>Hi</p><img alt="{% if vip %}VIP" title="badge{% endif %}" src="x">',
            'Hi',
        ],
        [
            'a condition that starts inside an address',
            '<a href="https://example.com/{% if vip %}a" title="x{% else %}b{% endif %}">Go</a>',
            'Go (https://example.com/a)',
        ],
        [
            'an address whose variable changes inside the link',
            '{% assign u = "https://example.com/old" %}<a href="{{ u }}">{% assign u = "https://example.com/new" %}Go</a>',
            'https://example.com/old Go',
        ],
        ['a conditional class on a link with no address', '<a {% if vip %}class="b"{% endif %}>Go</a>', 'Go'],
        ['a raw block that opens in a comment', '<!--[if mso]>{% raw %}<![endif]-->{{#x}}{% endraw %}', '{{#x}}'],
        [
            'a loop over table rows',
            '<table>{% for item in items %}<tr><td><a href="{{ item.url }}">{{ item.name }}</a></td></tr>{% endfor %}</table>',
            'One (https://example.com/1)\nTwo (https://example.com/2)',
        ],
        [
            'a link that depends on a condition',
            '{% if vip %}<a href="https://example.com/vip">{% else %}<a href="https://example.com/all">{% endif %}Go</a>',
            'https://example.com/vip Go',
        ],
    ])('renders %s', (_name, html, expected) => {
        const items = [
            { name: 'One', url: 'https://example.com/1' },
            { name: 'Two', url: 'https://example.com/2' },
        ]

        expect(LiquidRenderer.render(htmlToEmailText(html), { vip: true, name: 'Ada', items }).trim()).toEqual(expected)
    })

    it.each([
        ['the same words and links', 'Shop\n\nBye (https://example.com)', true],
        ['other words', 'Shop now\nBye (https://example.com)', false],
    ])('recognizes a text with %s', (_name, text, expected) => {
        expect(isTextOfHtml(text, '<p>Shop</p><a href="https://example.com">Bye</a>')).toBe(expected)
    })

    it('recognizes addresses another writer formats differently', () => {
        const html =
            '<a href="https://example.com"><img alt="Logo"></a><p><a href="mailto:a@example.com">a@example.com</a></p>'

        expect(isTextOfHtml('(https://example.com)\na@example.com (mailto:a@example.com)', html)).toBe(true)
    })
})
