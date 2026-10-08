package ratelimit

import (
	"container/list"
	"errors"
	"math"
	"sync"
	"time"
)

type Config struct {
	Capacity     float64
	RefillPerSec float64
	MaxEntries   int
	IdleTTL      time.Duration
}

type Limiter struct {
	mu      sync.Mutex
	config  Config
	entries map[string]*entry
	recency *list.List
	now     func() time.Time
}

type entry struct {
	tokens     float64
	updatedAt  time.Time
	lastAccess time.Time
	element    *list.Element
}

func New(config Config) (*Limiter, error) {
	return newLimiter(config, time.Now)
}

func newLimiter(config Config, now func() time.Time) (*Limiter, error) {
	if config.Capacity <= 0 || math.IsNaN(config.Capacity) || math.IsInf(config.Capacity, 0) ||
		config.RefillPerSec <= 0 || math.IsNaN(config.RefillPerSec) || math.IsInf(config.RefillPerSec, 0) ||
		config.MaxEntries <= 0 || config.IdleTTL <= 0 {
		return nil, errors.New("rate limit values must be positive")
	}
	return &Limiter{config: config, entries: make(map[string]*entry), recency: list.New(), now: now}, nil
}

func (l *Limiter) Allow(key string) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := l.now()
	current, exists := l.entries[key]
	if !exists || now.Sub(current.lastAccess) >= l.config.IdleTTL {
		if exists {
			l.recency.Remove(current.element)
			delete(l.entries, key)
		}
		if len(l.entries) >= l.config.MaxEntries {
			l.removeLeastRecentlyUsed()
		}
		current = &entry{tokens: l.config.Capacity, updatedAt: now}
		current.element = l.recency.PushBack(key)
		l.entries[key] = current
	} else {
		l.recency.MoveToBack(current.element)
	}
	elapsed := now.Sub(current.updatedAt).Seconds()
	current.tokens = math.Min(l.config.Capacity, current.tokens+elapsed*l.config.RefillPerSec)
	current.updatedAt = now
	current.lastAccess = now
	if current.tokens >= 1 {
		current.tokens--
		return true, 0
	}
	retryAfter := time.Duration(math.Ceil((1-current.tokens)/l.config.RefillPerSec*float64(time.Second))) * time.Nanosecond
	return false, retryAfter
}

func (l *Limiter) removeLeastRecentlyUsed() {
	oldest := l.recency.Front()
	if oldest == nil {
		return
	}
	delete(l.entries, oldest.Value.(string))
	l.recency.Remove(oldest)
}
