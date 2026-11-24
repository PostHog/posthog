package telemetry

import (
	"net/http"
	"slices"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type Metrics struct {
	registry *prometheus.Registry
	requests *prometheus.CounterVec
	duration *prometheus.HistogramVec
	failures *prometheus.CounterVec
	reloads  *prometheus.CounterVec
}

func NewMetrics() *Metrics {
	m := &Metrics{
		registry: prometheus.NewRegistry(),
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_requests_total", Help: "Completed egress requests."}, []string{"outcome"}),
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "egress_request_duration_seconds", Help: "Egress request duration."}, []string{"outcome"}),
		failures: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_relay_failures_total", Help: "Relay transport failures."}, []string{"kind"}),
		reloads:  prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_reload_total", Help: "Configuration reload attempts."}, []string{"outcome"}),
	}
	m.registry.MustRegister(m.requests, m.duration, m.failures, m.reloads)
	return m
}

func boundedLabel(value string, allowed ...string) string {
	if slices.Contains(allowed, value) {
		return value
	}
	return "other"
}

func (m *Metrics) Request(outcome string, duration time.Duration) {
	outcome = boundedLabel(outcome, "allowed", "denied", "unavailable", "invalid_request", "not_found", "audit_unavailable", "rate_limited", "canceled", "completed")
	m.requests.WithLabelValues(outcome).Inc()
	m.duration.WithLabelValues(outcome).Observe(duration.Seconds())
}

func (m *Metrics) RelayFailure(kind string) {
	m.failures.WithLabelValues(boundedLabel(kind, "canceled", "tls_verification", "dns", "timeout", "connect")).Inc()
}

func (m *Metrics) Reload(outcome string) {
	m.reloads.WithLabelValues(boundedLabel(outcome, "success", "failure")).Inc()
}

func (m *Metrics) BindAudit(a *Audit) {
	m.registry.MustRegister(
		prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "egress_audit_pending_events", Help: "Queued, exporting or reserved audit events."}, func() float64 {
			a.mu.Lock()
			defer a.mu.Unlock()
			return float64(a.occupied)
		}),
		prometheus.NewCounterFunc(prometheus.CounterOpts{Name: "egress_audit_rejected_total", Help: "Requests refused because audit capacity is unavailable."}, func() float64 {
			a.mu.Lock()
			defer a.mu.Unlock()
			return float64(a.rejected)
		}),
		prometheus.NewGaugeFunc(prometheus.GaugeOpts{Name: "egress_audit_export_failed", Help: "Whether audit output has failed and requires restart."}, func() float64 {
			if a.Failed() {
				return 1
			}
			return 0
		}),
	)
}

func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{DisableCompression: true})
}
