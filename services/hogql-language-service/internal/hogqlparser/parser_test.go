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

func TestDecodeNestedArraysAndWindowNames(t *testing.T) {
	const input = `{"node":"SelectQuery","start":{"offset":0},"end":{"offset":20},"select":[{"node":"Dict","items":[[{"node":"Constant","start":{"offset":1},"end":{"offset":2}},{"node":"Field","start":{"offset":3},"end":{"offset":4}}]]}],"window_exprs":{"start":{"node":"WindowExpr","partition_by":[{"node":"Field","start":{"offset":5},"end":{"offset":6}}]}}}`
	root, err := decode("01234567890123456789", []byte(input))
	if err != nil {
		t.Fatal(err)
	}
	items := root.Child("select").Children("items")
	if len(items) != 2 || items[1].Kind != "Field" {
		t.Fatalf("nested items: %#v", items)
	}
	window := root.Child("window_exprs").Child("start")
	if window == nil || window.Kind != "WindowExpr" || window.Child("partition_by") == nil {
		t.Fatalf("window: %#v", window)
	}
	count := 0
	root.Walk(func(n *Node) bool {
		if n.Kind == "Field" {
			count++
		}
		return true
	})
	if count != 2 {
		t.Fatalf("walk found %d fields", count)
	}
}

func TestParseSelectRejectsInvalidUTF8(t *testing.T) {
	_, err := ParseSelect("SELECT \xff")
	if _, ok := err.(*SyntaxError); !ok {
		t.Fatalf("expected syntax error, got %v", err)
	}
}
