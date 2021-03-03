import { createServer } from '../src/server'
import { PluginsServer } from '../src/types'
import { code } from '../src/utils'
import { transformCode } from '../src/vm/transforms'
import { resetTestDatabase } from './helpers/sql'

let server: PluginsServer
let closeServer: () => Promise<void>
beforeEach(async () => {
    ;[server, closeServer] = await createServer()
    await resetTestDatabase(`const processEvent = event => event`)
})
afterEach(async () => {
    await closeServer()
})

describe('transformCode', () => {
    it('secures awaits by wrapping promises in __asyncGuard', () => {
        const rawCode = code`
            async function x() {
              await console.log()
            }
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(console.log());
            }
        `)
    })

    it('secures then calls by wrapping promises in __asyncGuard', () => {
        const rawCode = code`
            async function x() {}
            x.then(() => null)
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {}

            __asyncGuard(x).then(() => null);
        `)
    })

    it('secures block for loops with timeouts', () => {
        const rawCode = code`
            for (let i = 0; i < i + 1; i++) {
                console.log(i)
            }
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = Date.now();

            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 1:0");
              console.log(i);
            }
        `)
    })

    it('secures inline for loops with timeouts', () => {
        const rawCode = code`
            for (let i = 0; i < i + 1; i++) console.log(i)
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = Date.now();

            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 1:0");
              console.log(i);
            }
        `)
    })

    it('secures block for loops with timeouts avoiding _LP collision', () => {
        const rawCode = code`
            const _LP = 0

            for (let i = 0; i < i + 1; i++) {
                console.log(i)
            }
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = 0;

            const _LP2 = Date.now();

            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP2 > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 3:0");
              console.log(i);
            }
        `)
    })

    it('transforms TypeScript to plain JavaScript', () => {
        const rawCode = code`
            interface Y {
              a: int
              b: string
            }

            function k({ a, b }: Y): string {
                return \`a * 10 is {a * 10}, while b is just {b}\`
            }

            let a: int = 2
            console.log(k({ a, b: 'tomato' }))
        `

        const transformedCode = transformCode(rawCode, server)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            function k({
              a,
              b
            }) {
              return \`a * 10 is {a * 10}, while b is just {b}\`;
            }

            let a = 2;
            console.log(k({
              a,
              b: 'tomato'
            }));
        `)
    })
})
