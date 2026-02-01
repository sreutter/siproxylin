package main

import (
	"bufio"
	"fmt"
	"log/slog"
	"os/exec"
	"strings"

	pb "github.com/yourusername/drunk-call-service/proto"
)

// ListAudioDevices enumerates available audio input/output devices using pactl
// (GStreamer DeviceMonitor crashes with nil caps, so we use pactl instead)
func ListAudioDevices(logger *slog.Logger) ([]*pb.AudioDevice, error) {
	logger.Info("ListAudioDevices called - starting device enumeration via pactl")

	var audioDevices []*pb.AudioDevice

	// Get sinks (speakers/outputs)
	sinks, err := getPactlDevices(logger, "sinks")
	if err != nil {
		logger.Error("Failed to get sinks", "error", err)
	} else {
		for _, dev := range sinks {
			audioDevices = append(audioDevices, &pb.AudioDevice{
				Name:        dev.Name,
				Description: dev.Description,
				DeviceClass: "Audio/Sink",
			})
			logger.Debug("Found audio sink", "name", dev.Name, "description", dev.Description)
		}
	}

	// Get sources (microphones/inputs) - exclude monitor devices
	sources, err := getPactlDevices(logger, "sources")
	if err != nil {
		logger.Error("Failed to get sources", "error", err)
	} else {
		for _, dev := range sources {
			// Skip monitor devices (loopback from outputs)
			if strings.Contains(dev.Name, ".monitor") {
				continue
			}
			audioDevices = append(audioDevices, &pb.AudioDevice{
				Name:        dev.Name,
				Description: dev.Description,
				DeviceClass: "Audio/Source",
			})
			logger.Debug("Found audio source", "name", dev.Name, "description", dev.Description)
		}
	}

	logger.Info("Audio device enumeration complete", "total_devices", len(audioDevices))
	return audioDevices, nil
}

type pactlDevice struct {
	Name        string
	Description string
}

// getPactlDevices parses pactl output to get device names and descriptions
func getPactlDevices(logger *slog.Logger, deviceType string) ([]pactlDevice, error) {
	// Run pactl list sinks/sources
	cmd := exec.Command("pactl", "list", deviceType)
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("failed to run pactl list %s: %w", deviceType, err)
	}

	var devices []pactlDevice
	var currentName string
	var currentDesc string

	scanner := bufio.NewScanner(strings.NewReader(string(output)))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		if strings.HasPrefix(line, "Name:") {
			currentName = strings.TrimSpace(strings.TrimPrefix(line, "Name:"))
		} else if strings.HasPrefix(line, "Description:") {
			currentDesc = strings.TrimSpace(strings.TrimPrefix(line, "Description:"))

			// When we have both name and description, create device
			if currentName != "" && currentDesc != "" {
				devices = append(devices, pactlDevice{
					Name:        currentName,
					Description: currentDesc,
				})
				currentName = ""
				currentDesc = ""
			}
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("failed to parse pactl output: %w", err)
	}

	logger.Debug("Parsed pactl devices", "type", deviceType, "count", len(devices))
	return devices, nil
}
