function wait(ms) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

async function something() {
    setTimeout(() => console.log('timeout called'), 1000)

    let roll = true

    while (roll) {
        await wait(3000)
        console.log('while')
        roll = false
    }
}

something()
