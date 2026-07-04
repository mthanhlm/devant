// Bench fixture: the golden symbols/edges live in expected.json next to this file.
package sample

import (
	"encoding/json"
	"os"
)

type Store struct {
	Path string
}

func (s *Store) Load() (map[string]any, error) {
	raw, err := os.ReadFile(s.Path)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	err = json.Unmarshal(raw, &out)
	return out, err
}

func ReadConfig(path string) (map[string]any, error) {
	s := &Store{Path: path}
	return s.Load()
}
