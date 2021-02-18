import { createServer } from '../src/server'
import { PluginsServer } from '../src/types'
import { code } from '../src/utils'
import { secureCode } from '../src/vm/transforms'
import { resetTestDatabase } from './helpers/sql'

let server: PluginsServer
let closeServer: () => Promise<void>
beforeEach(async () => {
    ;[server, closeServer] = await createServer()
    await resetTestDatabase(`const processEvent = event => event`)
})
afterEach(() => {
    closeServer()
})

describe('secureCode', () => {
    it('secures awaits by wrapping promises in __asyncGuard', () => {
        const rawCode = code`
            async function x() {
              await console.log()
            }
        `

        const securedCode = secureCode(rawCode, server)

        expect(securedCode).toStrictEqual(code`
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

        const securedCode = secureCode(rawCode, server)

        expect(securedCode).toStrictEqual(code`
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

        const securedCode = secureCode(rawCode, server)

        expect(securedCode).toStrictEqual(code`
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

        const securedCode = secureCode(rawCode, server)

        expect(securedCode).toStrictEqual(code`
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

        const securedCode = secureCode(rawCode, server)

        expect(securedCode).toStrictEqual(code`
            "use strict";

            const _LP = 0;

            const _LP2 = Date.now();

            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP2 > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 3:0");
              console.log(i);
            }
        `)
    })
})
