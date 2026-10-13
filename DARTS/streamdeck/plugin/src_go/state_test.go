package main

import (
	"encoding/json"
	"fmt"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestPerStateImageSettings(t *testing.T) {
	fields := map[string]string{
		"on": "imageOn", "off": "imageOff", "pending": "imagePending",
		"error": "imageError", "offline": "imageOffline", "no_map": "imageNoMap", "stale": "imageStale",
	}
	input := make(map[string]string)
	for status, field := range fields {
		input[field] = " /art/" + status + ".png "
	}
	data, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	var settings KeySettings
	if err := json.Unmarshal(data, &settings); err != nil {
		t.Fatal(err)
	}
	data, err = json.Marshal(settings)
	if err != nil {
		t.Fatal(err)
	}
	var output map[string]string
	if err := json.Unmarshal(data, &output); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(input, output) {
		t.Fatalf("settings round-trip: got %v, want %v", output, input)
	}
	normalized := NormalizeSettings("map", settings)
	for status := range fields {
		if got := normalized.ImagePath(status); got != "/art/"+status+".png" {
			t.Errorf("%s image path: %q", status, got)
		}
		if got := NormalizeSettings("map", KeySettings{}).ImagePath(status); got != "" {
			t.Errorf("%s default image path: %q", status, got)
		}
	}
	if got := normalized.ImagePath("unknown"); got != "" {
		t.Errorf("unknown status image path: %q", got)
	}
}

func boolPtr(b bool) *bool {
	return &b
}

func intPtr(i int) *int {
	return &i
}

func TestStateModel(t *testing.T) {
	seq := 0
	uuidGen := func() string {
		seq++
		return fmt.Sprintf("uuid-%d", seq)
	}

	model := CreateModel()
	if model.ConnectionState != "offline" {
		t.Fatalf("expected offline, got %s", model.ConnectionState)
	}

	now := time.Unix(0, 0)
	for _, ctrl := range []string{"map", "ifr", "vfr"} {
		if st := model.KeyStatus(ctrl, now); st != "offline" {
			t.Fatalf("expected offline for %s, got %s", ctrl, st)
		}
	}

	res := model.BeginCommand("ifr", now, uuidGen)
	if res.Ok || res.Reason != "offline" {
		t.Fatalf("expected offline error, got %+v", res)
	}

	// Apply connected snapshot
	model.ApplySnapshot(&UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(false),
		VfrEnabled:      boolPtr(true),
		Revision:        intPtr(1),
	})

	if st := model.KeyStatus("map", now); st != "on" {
		t.Fatalf("expected map on, got %s", st)
	}
	if st := model.KeyStatus("ifr", now); st != "off" {
		t.Fatalf("expected ifr off, got %s", st)
	}
	if st := model.KeyStatus("vfr", now); st != "on" {
		t.Fatalf("expected vfr on, got %s", st)
	}

	// Begin command: internally pending, but KeyStatus retains confirmed state to avoid WAIT flash
	cmdNow := time.Unix(1, 0)
	begin := model.BeginCommand("ifr", cmdNow, uuidGen)
	if !begin.Ok || begin.RequestId != "sd-uuid-1" || begin.Command != "toggle_ifr" {
		t.Fatalf("unexpected begin result: %+v", begin)
	}
	if model.PendingCommand == nil || model.PendingCommand.RequestId != "sd-uuid-1" {
		t.Fatalf("expected pending command to be tracked internally")
	}
	if st := model.KeyStatus("ifr", cmdNow); st != "off" {
		t.Fatalf("expected ifr to retain confirmed 'off' state during pending, got %s", st)
	}
	if st := model.KeyStatus("map", cmdNow); st != "on" {
		t.Fatalf("expected map still on, got %s", st)
	}

	// Cannot begin second command while one is pending
	second := model.BeginCommand("map", cmdNow, uuidGen)
	if second.Ok || second.Reason != "pending" {
		t.Fatalf("expected pending rejection, got %+v", second)
	}

	// Unrelated report does not confirm
	model.ApplySnapshot(&UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(false),
		VfrEnabled:      boolPtr(true),
		LastRequestId:   "other",
	})
	if model.PendingCommand == nil {
		t.Fatalf("expected pendingCommand to remain active")
	}
	if st := model.KeyStatus("ifr", cmdNow.Add(100*time.Millisecond)); st != "off" {
		t.Fatalf("expected ifr to remain confirmed 'off' until confirmed, got %s", st)
	}

	// Matching report confirms
	model.ApplySnapshot(&UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(true),
		VfrEnabled:      boolPtr(true),
		LastRequestId:   "sd-uuid-1",
	})
	if model.PendingCommand != nil {
		t.Fatalf("expected pendingCommand to be nil after confirmation")
	}
	if st := model.KeyStatus("ifr", cmdNow.Add(200*time.Millisecond)); st != "on" {
		t.Fatalf("expected ifr on, got %s", st)
	}

	// Timeout into ERROR
	timeoutStart := time.Unix(2, 0)
	timed := model.BeginCommand("vfr", timeoutStart, uuidGen)
	if !timed.Ok {
		t.Fatalf("failed to begin vfr command: %+v", timed)
	}
	if model.ExpirePending(timeoutStart.Add(ConfirmTimeout - time.Millisecond)) {
		t.Fatalf("should not have expired before timeout")
	}
	if !model.ExpirePending(timeoutStart.Add(ConfirmTimeout)) {
		t.Fatalf("should have expired at timeout")
	}
	if model.PendingCommand != nil {
		t.Fatalf("expected pendingCommand cleared")
	}
	if st := model.KeyStatus("vfr", timeoutStart.Add(ConfirmTimeout+time.Millisecond)); st != "error" {
		t.Fatalf("expected error status, got %s", st)
	}
	if st := model.KeyStatus("vfr", timeoutStart.Add(ConfirmTimeout+ErrorHoldDuration+time.Millisecond)); st != "on" {
		t.Fatalf("expected return to live status on, got %s", st)
	}
}

func TestSvgRendering(t *testing.T) {
	rectRe := regexp.MustCompile(`<rect[^>]*fill="([^"]+)"`)
	for _, tc := range []struct {
		status string
		color  string
		text   string
	}{
		{"on", DefaultColors["colorOn"], "ON"},
		{"off", DefaultColors["colorOff"], "OFF"},
		{"pending", DefaultColors["colorPending"], "WAIT"},
		{"error", DefaultColors["colorPending"], "ERROR"},
		{"offline", DefaultColors["colorOffline"], "OFFLINE"},
		{"no_map", DefaultColors["colorNoMap"], "NO MAP"},
		{"stale", DefaultColors["colorNoMap"], "STALE"},
	} {
		svg := RenderKeySvg("ifr", tc.status, KeySettings{}, "")
		m := rectRe.FindStringSubmatch(svg)
		if len(m) < 2 || m[1] != tc.color {
			t.Fatalf("for status %s, expected color %s, got %v", tc.status, tc.color, m)
		}
		if !strings.Contains(svg, fmt.Sprintf(">%s</text>", tc.text)) {
			t.Fatalf("for status %s, missing text %s in %s", tc.status, tc.text, svg)
		}
		if !strings.Contains(svg, ">IFR</text>") {
			t.Fatalf("missing >IFR</text> in %s", svg)
		}
	}

	// Custom settings with XML escaping
	customSvg := RenderKeySvg("map", "on", KeySettings{
		Label:    " <B&> ",
		ColorOn:  "#00ff00",
		ColorOff: "red\" onload=\"x",
	}, "")
	m := rectRe.FindStringSubmatch(customSvg)
	if len(m) < 2 || m[1] != "#00ff00" {
		t.Fatalf("expected #00ff00, got %v", m)
	}
	if !strings.Contains(customSvg, ">&lt;B&amp;&gt;</text>") {
		t.Fatalf("expected escaped XML label, got %s", customSvg)
	}

	// Invalid color falls back to default
	offSvg := RenderKeySvg("map", "off", KeySettings{ColorOff: "red\" onload=\"x"}, "")
	mOff := rectRe.FindStringSubmatch(offSvg)
	if len(mOff) < 2 || mOff[1] != DefaultColors["colorOff"] {
		t.Fatalf("expected fallback colorOff, got %v", mOff)
	}

	// Max label length
	norm := NormalizeSettings("vfr", KeySettings{Label: "ABCDEFGHIJKLMN"})
	if norm.Label != "ABCDEFGHIJ" {
		t.Fatalf("expected truncated label ABCDEFGHIJ, got %s", norm.Label)
	}

	// Icon data uri
	icon := "data:image/png;base64,iVBORw0KGgo="
	iconSvg := RenderKeySvg("vfr", "on", KeySettings{}, icon)
	if !strings.Contains(iconSvg, fmt.Sprintf(`<image href="%s"`, icon)) {
		t.Fatalf("expected icon image element in %s", iconSvg)
	}

	// Invalid icon URI rejected
	badIconSvg := RenderKeySvg("vfr", "on", KeySettings{}, "javascript:alert(1)")
	if strings.Contains(badIconSvg, "<image") {
		t.Fatalf("expected bad icon to be ignored in %s", badIconSvg)
	}

	// Text contrast for light vs dark backgrounds
	if tc := TextColorForBackground(DefaultColors["colorOffline"]); tc != "#0F172A" {
		t.Fatalf("expected dark text for light neutral offline color %s, got %s", DefaultColors["colorOffline"], tc)
	}
	if tc := TextColorForBackground(DefaultColors["colorOn"]); tc != "#FFFFFF" {
		t.Fatalf("expected white text for dark green on color %s, got %s", DefaultColors["colorOn"], tc)
	}
}
