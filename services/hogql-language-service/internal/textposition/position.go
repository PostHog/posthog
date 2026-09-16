package textposition

import "fmt"

type Encoding string

const (
	UTF8  Encoding = "utf-8"
	UTF16 Encoding = "utf-16"
)

func (e Encoding) Valid() bool {
	return e == UTF8 || e == UTF16
}

func ToByteOffset(value string, offset int, encoding Encoding) (int, error) {
	if !encoding.Valid() {
		return 0, fmt.Errorf("unsupported position encoding %q", encoding)
	}
	if offset < 0 {
		return len(value), nil
	}
	if encoding == UTF8 {
		if offset > len(value) {
			return len(value), nil
		}
		return offset, nil
	}

	utf16Offset := 0
	for byteOffset, character := range value {
		if utf16Offset >= offset {
			return byteOffset, nil
		}
		characterWidth := 1
		if character > 0xFFFF {
			characterWidth = 2
		}
		if utf16Offset+characterWidth > offset {
			return byteOffset, nil
		}
		utf16Offset += characterWidth
	}
	return len(value), nil
}

func FromByteOffset(value string, offset int, encoding Encoding) (int, error) {
	if !encoding.Valid() {
		return 0, fmt.Errorf("unsupported position encoding %q", encoding)
	}
	if offset < 0 {
		offset = 0
	} else if offset > len(value) {
		offset = len(value)
	}
	if encoding == UTF8 {
		return offset, nil
	}

	utf16Offset := 0
	for byteOffset, character := range value {
		if byteOffset >= offset {
			break
		}
		utf16Offset++
		if character > 0xFFFF {
			utf16Offset++
		}
	}
	return utf16Offset, nil
}
