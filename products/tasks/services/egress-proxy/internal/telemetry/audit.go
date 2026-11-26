package telemetry

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"sync"
	"time"
)

var ErrUnavailable = errors.New("audit output unavailable")

type Event struct {
	SchemaVersion     int       `json:"schema_version"`
	Time              time.Time `json:"time"`
	RequestID         string    `json:"request_id"`
	RelayKeySHA256    string    `json:"relay_key_sha256,omitempty"`
	Phase             string    `json:"phase"`
	TeamID            int64     `json:"team_id,omitempty"`
	RunID             string    `json:"run_id,omitempty"`
	ExecutionID       string    `json:"execution_id,omitempty"`
	ActorID           int64     `json:"actor_id,omitempty"`
	ActorEpoch        uint64    `json:"actor_epoch,omitempty"`
	Operation         string    `json:"operation"`
	Outcome           string    `json:"outcome"`
	Status            int       `json:"status"`
	DurationMS        float64   `json:"duration_ms"`
	CredentialVersion string    `json:"credential_version,omitempty"`
	BytesReceived     int64     `json:"bytes_received,omitempty"`
	BytesSent         int64     `json:"bytes_sent,omitempty"`
}

type Audit struct {
	mu       sync.Mutex
	queue    chan Event
	done     chan struct{}
	occupied int
	active   int
	rejected uint64
	closing  bool
	failed   bool
}

type Record struct {
	audit   *Audit
	emitted int
}

func NewAudit(writer io.Writer, capacity int) (*Audit, error) {
	if writer == nil || capacity < 2 {
		return nil, errors.New("invalid audit configuration")
	}
	audit := &Audit{queue: make(chan Event, capacity), done: make(chan struct{})}
	go audit.export(writer)
	return audit, nil
}

func (a *Audit) export(writer io.Writer) {
	defer close(a.done)
	encoder := json.NewEncoder(writer)
	for event := range a.queue {
		err := encoder.Encode(event)
		a.mu.Lock()
		if err != nil {
			a.failed = true
			a.mu.Unlock()
			return
		}
		a.occupied--
		a.mu.Unlock()
	}
}

func (a *Audit) TryReserve() (*Record, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closing || a.failed || a.occupied+2 > cap(a.queue) {
		a.rejected++
		return nil, false
	}
	a.occupied += 2
	a.active++
	return &Record{audit: a}, true
}

func (r *Record) Emit(event Event) bool {
	a := r.audit
	a.mu.Lock()
	defer a.mu.Unlock()
	if r.emitted == 2 {
		return false
	}
	event.SchemaVersion = 1
	event.Time = time.Now().UTC()
	event.Phase = "admission"
	if r.emitted == 1 {
		event.Phase = "completion"
	}
	a.queue <- event
	r.emitted++
	if r.emitted == 2 {
		a.active--
		if a.closing && a.active == 0 {
			close(a.queue)
		}
	}
	return true
}

func (a *Audit) Failed() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.failed
}

func (a *Audit) Healthy() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return !a.closing && !a.failed
}

func (a *Audit) Close(ctx context.Context) error {
	a.mu.Lock()
	if !a.closing {
		a.closing = true
		if a.active == 0 {
			close(a.queue)
		}
	}
	a.mu.Unlock()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-a.done:
		a.mu.Lock()
		defer a.mu.Unlock()
		if a.failed {
			return ErrUnavailable
		}
		return nil
	}
}
