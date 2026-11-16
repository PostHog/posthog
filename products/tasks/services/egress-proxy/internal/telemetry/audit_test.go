package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"sync"
	"testing"
	"testing/synctest"
)

type blockedWriter struct {
	bytes.Buffer
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func (w *blockedWriter) Write(data []byte) (int, error) {
	w.once.Do(func() {
		close(w.started)
		<-w.release
	})
	return w.Buffer.Write(data)
}

type failedWriter struct{}

func (failedWriter) Write([]byte) (int, error) {
	return 0, errors.New("synthetic output failure")
}

func TestAuditCapacityAndRecovery(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		writer := &blockedWriter{started: make(chan struct{}), release: make(chan struct{})}
		audit, err := NewAudit(writer, 2)
		if err != nil {
			t.Fatal(err)
		}
		record, ok := audit.TryReserve()
		if !ok {
			t.Fatal("initial reservation rejected")
		}
		event := Event{RequestID: "request-example", Operation: "probe", Outcome: "allowed", TeamID: 123}
		record.Emit(event)
		<-writer.started
		if _, ok := audit.TryReserve(); ok {
			t.Fatal("unfinished request's completion capacity was reused")
		}
		record.Emit(event)
		if _, ok := audit.TryReserve(); ok || !audit.Healthy() || audit.Failed() {
			t.Fatal("blocked output must reject admission without failing health")
		}
		close(writer.release)
		synctest.Wait()
		next, ok := audit.TryReserve()
		if !ok {
			t.Fatal("drained output did not restore admission")
		}
		next.Emit(Event{RequestID: "denied-example", Operation: "unknown", Outcome: "denied"})
		next.Emit(Event{RequestID: "denied-example", Operation: "unknown", Outcome: "denied"})
		if err := audit.Close(context.Background()); err != nil {
			t.Fatal(err)
		}
		decoder := json.NewDecoder(&writer.Buffer)
		for i := range 4 {
			var result map[string]any
			if err := decoder.Decode(&result); err != nil {
				t.Fatal(err)
			}
			if result["schema_version"] != float64(1) || result["phase"] != []string{"admission", "completion"}[i%2] || result["time"] == "" {
				t.Fatalf("invalid event envelope: %v", result)
			}
			if i >= 2 {
				if _, exists := result["team_id"]; exists {
					t.Fatal("unauthenticated audit record contains a team")
				}
			} else if result["team_id"] != float64(123) || result["request_id"] != "request-example" {
				t.Fatalf("trusted identity lost: %v", result)
			}
		}
		var extra Event
		if err := decoder.Decode(&extra); err != io.EOF {
			t.Fatalf("unexpected extra event: %v", err)
		}
	})
}

func TestAuditFailureStopsAdmission(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		audit, err := NewAudit(failedWriter{}, 8)
		if err != nil {
			t.Fatal(err)
		}
		record, _ := audit.TryReserve()
		record.Emit(Event{})
		synctest.Wait()
		if audit.Healthy() || !audit.Failed() {
			t.Fatal("output failure was not reported")
		}
		if _, ok := audit.TryReserve(); ok {
			t.Fatal("failed output still accepts requests")
		}
		record.Emit(Event{})
		if err := audit.Close(context.Background()); !errors.Is(err, ErrUnavailable) {
			t.Fatalf("close error = %v, want unavailable", err)
		}
	})
}

func TestAuditShutdown(t *testing.T) {
	for _, unfinished := range []bool{false, true} {
		name := "blocked output"
		if unfinished {
			name = "unfinished request"
		}
		t.Run(name, func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				writer := &blockedWriter{started: make(chan struct{}), release: make(chan struct{})}
				audit, err := NewAudit(writer, 8)
				if err != nil {
					t.Fatal(err)
				}
				record, _ := audit.TryReserve()
				record.Emit(Event{})
				<-writer.started
				if !unfinished {
					record.Emit(Event{})
				}
				ctx, cancel := context.WithCancel(context.Background())
				cancel()
				if err := audit.Close(ctx); !errors.Is(err, context.Canceled) {
					t.Fatalf("close error = %v, want cancellation", err)
				}
				if _, ok := audit.TryReserve(); ok || audit.Healthy() {
					t.Fatal("closing output still accepts new work")
				}
				if audit.Failed() {
					t.Fatal("planned shutdown reported an output failure")
				}
				if unfinished && !record.Emit(Event{}) {
					t.Fatal("closing output rejected a reserved completion")
				}
				close(writer.release)
				if err := audit.Close(context.Background()); err != nil {
					t.Fatal(err)
				}
				if record.Emit(Event{}) {
					t.Fatal("completed request emitted an extra event")
				}
			})
		})
	}
}
