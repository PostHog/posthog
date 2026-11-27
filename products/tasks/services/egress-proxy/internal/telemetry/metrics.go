package telemetry

import (
	"net/http"
	"slices"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type Metrics struct {
	registry     *prometheus.Registry
	requests     *prometheus.CounterVec
	duration     *prometheus.HistogramVec
	failures     *prometheus.CounterVec
	reloads      *prometheus.CounterVec
	certificates certificateCollector
	handler      http.Handler
	adminHandler http.Handler
}

func NewMetrics() *Metrics {
	m := &Metrics{
		registry: prometheus.NewRegistry(),
		requests: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_requests_total", Help: "Completed egress requests."}, []string{"outcome"}),
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{Name: "egress_request_duration_seconds", Help: "Egress request duration."}, []string{"outcome"}),
		failures: prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_relay_failures_total", Help: "Relay transport failures."}, []string{"kind"}),
		reloads:  prometheus.NewCounterVec(prometheus.CounterOpts{Name: "egress_reload_total", Help: "Configuration reload attempts."}, []string{"outcome"}),
	}
	m.certificates.description = prometheus.NewDesc("egress_certificate_expiration_timestamp_seconds", "Earliest expiry of certificates loaded for each TLS role.", []string{"role"}, nil)
	m.registry.MustRegister(m.requests, m.duration, m.failures, m.reloads, &m.certificates)
	for _, outcome := range []string{"success", "failure"} {
		m.reloads.WithLabelValues(outcome)
	}
	m.handler = m.scrapeHandler()
	m.adminHandler = m.scrapeHandler()
	return m
}

func boundedLabel(value string, allowed ...string) string {
	if slices.Contains(allowed, value) {
		return value
	}
	return "other"
}

func (m *Metrics) Request(outcome string, duration time.Duration) {
	outcome = boundedLabel(outcome, "allowed", "denied", "unavailable", "upstream_unavailable", "interrupted", "invalid_request", "not_found", "audit_unavailable", "rate_limited", "canceled", "completed")
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
	return m.handler
}

func (m *Metrics) AdminHandler() http.Handler {
	return m.adminHandler
}

func (m *Metrics) scrapeHandler() http.Handler {
	handler := promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{DisableCompression: true, MaxRequestsInFlight: 1})
	var mu sync.Mutex
	tokens, updated := float64(5), time.Now()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/metrics" || r.URL.RawPath != "" || r.URL.RawQuery != "" || r.URL.ForceQuery {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		mu.Lock()
		now := time.Now()
		tokens = min(5, tokens+now.Sub(updated).Seconds()*5)
		updated = now
		allowed := tokens >= 1
		if allowed {
			tokens--
		}
		mu.Unlock()
		if !allowed {
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		handler.ServeHTTP(w, r)
	})
}

type certificateCollector struct {
	mu          sync.RWMutex
	description *prometheus.Desc
	current     func() map[string]time.Time
}

func (c *certificateCollector) Describe(output chan<- *prometheus.Desc) {
	output <- c.description
}

func (c *certificateCollector) Collect(output chan<- prometheus.Metric) {
	c.mu.RLock()
	current := c.current
	c.mu.RUnlock()
	if current == nil {
		return
	}
	for role, expiry := range current() {
		output <- prometheus.MustNewConstMetric(c.description, prometheus.GaugeValue, float64(expiry.Unix()), role)
	}
}

func (m *Metrics) BindCertificates(current func() map[string]time.Time) {
	m.certificates.mu.Lock()
	defer m.certificates.mu.Unlock()
	m.certificates.current = current
}
