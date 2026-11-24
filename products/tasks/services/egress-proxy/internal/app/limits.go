package app

import (
	"math"
	"sync"
	"time"
)

const requestBurst = 512
const requestsPerSecond = 32

type requestBudget struct {
	tokens   float64
	updated  time.Time
	expires  time.Time
	reported time.Time
}

type requestLimits struct {
	mu      sync.Mutex
	entries map[string]*requestBudget
	maximum int
	now     func() time.Time
}

func newRequestLimits(maximum int) *requestLimits {
	return &requestLimits{entries: make(map[string]*requestBudget), maximum: maximum, now: time.Now}
}

func (l *requestLimits) admit(key string, expires time.Time) (allowed, report bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	budget := l.entries[key]
	if budget == nil {
		if len(l.entries) >= l.maximum {
			for existing, value := range l.entries {
				if !now.Before(value.expires) {
					delete(l.entries, existing)
				}
			}
		}
		if len(l.entries) >= l.maximum {
			return false, false
		}
		budget = &requestBudget{tokens: requestBurst, updated: now, expires: expires}
		l.entries[key] = budget
	}
	if expires.After(budget.expires) {
		budget.expires = expires
	}
	if now.After(budget.updated) {
		budget.tokens = math.Min(requestBurst, budget.tokens+now.Sub(budget.updated).Seconds()*requestsPerSecond)
		budget.updated = now
	}
	if budget.tokens >= 1 {
		budget.tokens--
		return true, false
	}
	if now.Sub(budget.reported) >= 10*time.Second {
		budget.reported = now
		return false, true
	}
	return false, false
}
