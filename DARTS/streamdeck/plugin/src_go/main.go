package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"

	"github.com/gorilla/websocket"
)

func parseArgs(argv []string) map[string]string {
	args := make(map[string]string)
	for i := 0; i < len(argv)-1; i++ {
		if strings.HasPrefix(argv[i], "-") {
			key := strings.TrimPrefix(argv[i], "-")
			args[key] = argv[i+1]
		}
	}
	return args
}

func main() {
	args := parseArgs(os.Args[1:])
	port := args["port"]
	pluginUUID := args["pluginUUID"]
	registerEvent := args["registerEvent"]

	if port == "" || pluginUUID == "" || registerEvent == "" {
		fmt.Fprintln(os.Stderr, "DARTS plugin must be launched by the Stream Deck app (-port, -pluginUUID, -registerEvent).")
		os.Exit(1)
	}

	u := url.URL{Scheme: "ws", Host: "127.0.0.1:" + port, Path: ""}
	conn, _, err := websocket.DefaultDialer.Dial(u.String(), nil)
	if err != nil {
		log.Fatalf("Failed to connect to Stream Deck WebSocket on port %s: %v", port, err)
	}
	defer conn.Close()

	var writeMu sync.Mutex
	send := func(msg any) {
		data, err := json.Marshal(msg)
		if err != nil {
			return
		}
		writeMu.Lock()
		defer writeMu.Unlock()
		_ = conn.WriteMessage(websocket.TextMessage, data)
	}

	plugin := NewDartsPlugin(PluginOptions{
		Send: send,
	})

	// Send registration and getGlobalSettings
	send(map[string]string{
		"event": registerEvent,
		"uuid":  pluginUUID,
	})
	send(map[string]string{
		"event":   "getGlobalSettings",
		"context": pluginUUID,
	})

	plugin.Start()
	defer plugin.Stop()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		plugin.Stop()
		conn.Close()
		os.Exit(0)
	}()

	for {
		_, message, err := conn.ReadMessage()
		if err != nil {
			break
		}
		plugin.HandleDeckMessage(message)
	}
}
