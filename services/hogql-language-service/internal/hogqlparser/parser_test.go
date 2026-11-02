package hogqlparser

import (
	"fmt"
	"sync"
	"testing"
)

func TestParseSelectKeepsConcurrentResultsApart(t *testing.T) {
	const workers = 32
	var wait sync.WaitGroup
	failures := make(chan string, workers)
	for worker := range workers {
		wait.Add(1)
		go func() {
			defer wait.Done()
			column := fmt.Sprintf("column_%d", worker)
			for range 20 {
				root, err := ParseSelect(fmt.Sprintf("SELECT %s FROM events WHERE %s > 0", column, column))
				if err != nil {
					failures <- err.Error()
					return
				}
				selected := root.Children("select")
				if len(selected) != 1 || len(selected[0].Chain()) != 1 || selected[0].Chain()[0] != column {
					failures <- fmt.Sprintf("worker %d parsed %#v", worker, selected)
					return
				}
			}
		}()
	}
	wait.Wait()
	close(failures)
	for failure := range failures {
		t.Error(failure)
	}
}
