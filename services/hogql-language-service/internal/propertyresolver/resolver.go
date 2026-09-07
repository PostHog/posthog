package propertyresolver

import (
	"regexp"
	"strings"
)

var groupOwner = regexp.MustCompile(`^group_?([0-4])$`)

func Resolve(parts []string, bindings map[string]string) (string, bool) {
	propertyIndex := -1
	for index, part := range parts {
		if strings.EqualFold(part, "properties") {
			propertyIndex = index
		}
	}
	if propertyIndex == -1 || propertyIndex != len(parts)-2 {
		return "", false
	}
	if propertyIndex > 0 {
		owner := strings.ToLower(parts[propertyIndex-1])
		if namespace, ok := namespaceForOwner(owner); ok {
			return namespace, true
		}
		if tableName, ok := bindings[owner]; ok {
			return namespaceForOwner(strings.ToLower(tableName))
		}
		return "", false
	}

	namespaces := map[string]bool{}
	for _, tableName := range bindings {
		if namespace, ok := namespaceForOwner(strings.ToLower(tableName)); ok {
			namespaces[namespace] = true
		}
	}
	if len(namespaces) != 1 {
		return "", false
	}
	for namespace := range namespaces {
		return namespace, true
	}
	return "", false
}

func namespaceForOwner(owner string) (string, bool) {
	switch owner {
	case "event", "events":
		return "event", true
	case "person", "persons":
		return "person", true
	case "session", "sessions":
		return "session", true
	}
	if match := groupOwner.FindStringSubmatch(owner); match != nil {
		return "group:" + match[1], true
	}
	return "", false
}
