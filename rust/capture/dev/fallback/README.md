# Capture Kafka degradation harness

This harness runs capture against two independent Redpanda clusters through Toxiproxy.
Prometheus collects capture and broker metrics, and Grafana provides a dashboard for local degradation testing.

## Start the harness

From this directory, run:

```bash
docker compose up --build --wait
```

Open Grafana at http://localhost:3001/d/capture-kafka-degradation.
Capture metrics are available at http://localhost:3308/metrics.

## Verify degradation reporting

Run:

```bash
./verify.sh
```

The check sends a healthy event, disables the primary Kafka proxy, waits for capture to report the disconnected broker, and confirms the affected request fails.
It restores the proxy before exiting.

To control the fault manually, run `./fault.sh degrade` or `./fault.sh restore`.
The secondary cluster remains healthy during the primary fault so both cluster metrics can be compared.

Stop the harness with:

```bash
docker compose down --volumes
```
