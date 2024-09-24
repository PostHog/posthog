const cyclotron = require('../.')

async function main() {

    console.log(cyclotron)

    cyclotron.initCyclotronMetrics({
        defaultLabels: { team: 'team1' },
        histogramBounds: [0, 1, 2, 3, 4, 5, 10, 20, 50, 100, 200, 500, 1000],
    })


    // loop forever, sleeping for a second, then logging the result of cyclotron.reportMetrics()
    for (;;) {
        cyclotron.emitFakeMetrics()
        await new Promise(resolve => setTimeout(resolve, 1000))
        console.log(JSON.stringify(cyclotron.getMetricsReport()))
    }
}

main()