package telemetry

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/synctest"
	"time"
)

func TestMetricsBoundLabelsAndSeparateFailures(t *testing.T) {
	metrics := NewMetrics()
	metrics.Request("denied", time.Second)
	metrics.Request("unavailable", time.Second)
	metrics.Request("upstream_unavailable", time.Second)
	metrics.Request("interrupted", time.Second)
	metrics.Request("run-secret-example", time.Second)
	metrics.RelayFailure("connect")
	metrics.RelayFailure("run-secret-example")
	metrics.Reload("failure")
	metrics.Reload("run-secret-example")
	response := httptest.NewRecorder()
	metrics.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	body := response.Body.String()
	for _, expected := range []string{
		`egress_requests_total{outcome="denied"} 1`,
		`egress_requests_total{outcome="unavailable"} 1`,
		`egress_requests_total{outcome="upstream_unavailable"} 1`,
		`egress_requests_total{outcome="interrupted"} 1`,
		`egress_request_duration_seconds_count{outcome="upstream_unavailable"} 1`,
		`egress_request_duration_seconds_count{outcome="interrupted"} 1`,
		`egress_requests_total{outcome="other"} 1`,
		`egress_relay_failures_total{kind="connect"} 1`,
		`egress_relay_failures_total{kind="other"} 1`,
		`egress_reload_total{outcome="failure"} 1`,
		`egress_reload_total{outcome="other"} 1`,
	} {
		if !strings.Contains(body, expected) {
			t.Fatalf("missing metric %q", expected)
		}
	}
	if strings.Contains(body, "run-secret-example") {
		t.Fatal("unbounded metric label escaped")
	}
	other := httptest.NewRecorder()
	NewMetrics().Handler().ServeHTTP(other, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if !strings.Contains(other.Body.String(), `egress_reload_total{outcome="failure"} 0`) {
		t.Fatal("reload failures have no baseline before the first attempt")
	}
	if strings.Contains(other.Body.String(), "egress_requests_total{") {
		t.Fatal("metrics leaked across service instances")
	}
}

func TestAuditExportFailureGauge(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		audit, err := NewAudit(failedWriter{}, 2)
		if err != nil {
			t.Fatal(err)
		}
		defer audit.Close(context.Background())
		metrics := NewMetrics()
		metrics.BindAudit(audit)
		assertFailureGauge := func(value string) {
			t.Helper()
			response := httptest.NewRecorder()
			metrics.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
			body := response.Body.String()
			if !strings.Contains(body, "# TYPE egress_audit_export_failed gauge\n") ||
				!strings.Contains(body, "egress_audit_export_failed "+value+"\n") {
				t.Fatalf("expected audit failure gauge %s, got %s", value, body)
			}
		}
		assertFailureGauge("0")
		record, ok := audit.TryReserve()
		if !ok {
			t.Fatal("initial reservation rejected")
		}
		record.Emit(Event{})
		record.Emit(Event{})
		synctest.Wait()
		assertFailureGauge("1")
	})
}

func TestMetricsScrapeAdmission(t *testing.T) {
	t.Run("listeners reserve separate collection slots", func(t *testing.T) {
		synctest.Test(t, func(t *testing.T) {
			metrics := NewMetrics()
			release := make(chan struct{})
			metrics.BindCertificates(func() map[string]time.Time {
				<-release
				return nil
			})
			responses := make(chan int, 2)
			for _, handler := range []func() http.Handler{metrics.Handler, metrics.AdminHandler} {
				go func() {
					response := httptest.NewRecorder()
					handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
					responses <- response.Code
				}()
			}
			synctest.Wait()
			for _, handler := range []func() http.Handler{metrics.Handler, metrics.AdminHandler} {
				overflow := make(chan int, 1)
				go func() {
					response := httptest.NewRecorder()
					handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
					overflow <- response.Code
				}()
				synctest.Wait()
				select {
				case status := <-overflow:
					if status != http.StatusServiceUnavailable {
						t.Errorf("overlapping scrape status = %d", status)
					}
				default:
					t.Error("overlapping scrape entered collection instead of being refused")
				}
			}
			close(release)
			for range 2 {
				if status := <-responses; status != http.StatusOK {
					t.Errorf("admitted scrape status = %d", status)
				}
			}
			synctest.Wait()
			for _, handler := range []func() http.Handler{metrics.Handler, metrics.AdminHandler} {
				response := httptest.NewRecorder()
				handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
				if response.Code != http.StatusOK {
					t.Fatalf("scrape did not recover after collection: %d", response.Code)
				}
			}
		})
	})
	for _, listener := range []string{"network", "admin"} {
		t.Run(listener+" budget", func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				metrics := NewMetrics()
				busy, idle := metrics.Handler, metrics.AdminHandler
				if listener == "admin" {
					busy, idle = idle, busy
				}
				scrape := func(handler func() http.Handler, want int) {
					t.Helper()
					response := httptest.NewRecorder()
					handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
					if response.Code != want {
						t.Fatalf("scrape status = %d, want %d", response.Code, want)
					}
				}
				for range 5 {
					scrape(busy, http.StatusOK)
				}
				scrape(busy, http.StatusServiceUnavailable)
				scrape(idle, http.StatusOK)
				time.Sleep(200 * time.Millisecond)
				scrape(busy, http.StatusOK)
				scrape(busy, http.StatusServiceUnavailable)
				time.Sleep(time.Hour)
				for range 5 {
					scrape(busy, http.StatusOK)
				}
				scrape(busy, http.StatusServiceUnavailable)
			})
		})
	}
}
