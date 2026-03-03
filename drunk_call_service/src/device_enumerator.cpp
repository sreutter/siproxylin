/**
 * Device Enumeration Implementation
 *
 * Cross-platform audio device enumeration using GStreamer's GstDeviceMonitor
 * Works on Linux (PulseAudio), Windows (WASAPI), macOS (CoreAudio)
 */

#include "media_session.h"
#include <gst/gst.h>
#include <iostream>
#include <algorithm>

#ifdef _WIN32
    #define OS_FAMILY "Windows"
#elif __APPLE__
    #define OS_FAMILY "macOS"
#else
    #define OS_FAMILY "Linux"
#endif

namespace drunk_call {

/**
 * Platform-specific device class filters
 * GStreamer automatically selects the appropriate provider per platform
 */
static const char* get_audio_source_classes() {
    // GStreamer picks the right provider:
    // - Linux: PulseAudio (pulsesrc)
    // - Windows: WASAPI (wasapisrc)
    // - macOS: CoreAudio (osxaudiosrc)
    return "Audio/Source";
}

static const char* get_audio_sink_classes() {
    // GStreamer picks the right provider:
    // - Linux: PulseAudio (pulsesink)
    // - Windows: WASAPI (wasapisink)
    // - macOS: CoreAudio (osxaudiosink)
    return "Audio/Sink";
}

static const char* get_video_source_classes() {
    // GStreamer picks the right provider:
    // - Linux: V4L2 (v4l2src)
    // - Windows: KsVideo (ksvideosrc)
    // - macOS: AVFoundation (avfvideosrc)
    return "Video/Source";
}

/**
 * Extract device ID from GstDevice
 * Platform-specific device ID formats:
 * - Linux (PulseAudio): "alsa_input.pci-..." or device index
 * - Windows (WASAPI): "{GUID}"
 * - macOS (CoreAudio): numeric ID
 */
static std::string extract_device_id(GstDevice *device) {
    std::string device_id;

    // Get device properties
    GstStructure *props = gst_device_get_properties(device);
    if (props) {
        const gchar *id = nullptr;

        // Platform-specific property names
        switch (OS_FAMILY[0]) {  // Cheap trick: 'L' = Linux, 'W' = Windows, 'm' = macOS
            case 'L':  // Linux - PulseAudio
                id = gst_structure_get_string(props, "device.name");
                if (!id) id = gst_structure_get_string(props, "device");
                break;

            case 'W':  // Windows - WASAPI
                id = gst_structure_get_string(props, "device.id");
                if (!id) id = gst_structure_get_string(props, "device");
                break;

            case 'm':  // macOS - CoreAudio
                id = gst_structure_get_string(props, "device.id");
                if (!id) id = gst_structure_get_string(props, "device");
                break;

            default:
                id = gst_structure_get_string(props, "device");
                break;
        }

        if (id) {
            device_id = id;
        }

        gst_structure_free(props);
    }

    // Fallback: use device name as ID
    if (device_id.empty()) {
        gchar *name = gst_device_get_display_name(device);
        if (name) {
            device_id = name;
            g_free(name);
        }
    }

    return device_id;
}

/**
 * Check if device is the default device
 */
static bool is_default_device(GstDevice *device) {
    GstStructure *props = gst_device_get_properties(device);
    if (!props) {
        return false;
    }

    bool is_default = false;

    // Platform-specific default detection
    switch (OS_FAMILY[0]) {
        case 'L':  // Linux - PulseAudio
            {
                const gchar *is_def = gst_structure_get_string(props, "is-default");
                is_default = (is_def && g_strcmp0(is_def, "true") == 0);
            }
            break;

        case 'W':  // Windows - WASAPI
            {
                gboolean def = FALSE;
                gst_structure_get_boolean(props, "device.default", &def);
                is_default = def;
            }
            break;

        case 'm':  // macOS - CoreAudio
            {
                gboolean def = FALSE;
                gst_structure_get_boolean(props, "device.default", &def);
                is_default = def;
            }
            break;

        default:
            break;
    }

    gst_structure_free(props);
    return is_default;
}

/**
 * Enumerate devices using GstDeviceMonitor
 */
std::vector<AudioDevice> DeviceEnumerator::enumerate_devices(const char *classes, bool is_input) {
    std::vector<AudioDevice> devices;

    try {
        std::cout << "[DeviceEnumerator] Enumerating " << (is_input ? "input" : "output")
                  << " devices on " << OS_FAMILY << "..." << std::endl;

        // Create device monitor - but DON'T start/stop it
        // Per GStreamer docs: get_devices() will probe hardware even if not started
        GstDeviceMonitor *monitor = gst_device_monitor_new();
        if (!monitor) {
            std::cerr << "[DeviceEnumerator] Failed to create device monitor" << std::endl;
            return devices;
        }

        // Add filter for this specific device class
        gst_device_monitor_add_filter(monitor, classes, nullptr);

        // Get devices WITHOUT start/stop - avoids PipeWire double-free bug
        // Docs say: "may actually probe the hardware if the monitor is not currently started"
        GList *device_list = gst_device_monitor_get_devices(monitor);

        for (GList *l = device_list; l != nullptr; l = l->next) {
            GstDevice *device = GST_DEVICE(l->data);

            AudioDevice audio_dev;
            audio_dev.is_input = is_input;

            // Get device ID
            audio_dev.id = extract_device_id(device);

            // Get display name
            gchar *display_name = gst_device_get_display_name(device);
            if (display_name) {
                audio_dev.name = display_name;
                g_free(display_name);
            }

            // Get device class (fuller description)
            gchar *device_class = gst_device_get_device_class(device);
            if (device_class) {
                audio_dev.description = device_class;
                g_free(device_class);
            }

            // Check if default
            audio_dev.is_default = is_default_device(device);

            std::cout << "[DeviceEnumerator]   " << (audio_dev.is_default ? "✓ " : "  ")
                      << audio_dev.name << " (id: " << audio_dev.id << ")" << std::endl;

            devices.push_back(audio_dev);
            gst_object_unref(device);
        }

        g_list_free(device_list);

        // Cleanup - no start/stop needed, just unref
        gst_object_unref(monitor);

        std::cout << "[DeviceEnumerator] Found " << devices.size() << " devices" << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "[DeviceEnumerator] Exception: " << e.what() << std::endl;
    }

    return devices;
}

std::vector<AudioDevice> DeviceEnumerator::list_audio_inputs() {
    return enumerate_devices(get_audio_source_classes(), true);
}

std::vector<AudioDevice> DeviceEnumerator::list_audio_outputs() {
    return enumerate_devices(get_audio_sink_classes(), false);
}

AudioDevice DeviceEnumerator::get_default_input() {
    auto devices = list_audio_inputs();

    // Find default device
    auto it = std::find_if(devices.begin(), devices.end(),
                          [](const AudioDevice &dev) { return dev.is_default; });

    if (it != devices.end()) {
        return *it;
    }

    // Fallback: return first device or empty
    if (!devices.empty()) {
        std::cout << "[DeviceEnumerator] No default input found, using first device" << std::endl;
        return devices[0];
    }

    std::cerr << "[DeviceEnumerator] No input devices found!" << std::endl;
    return AudioDevice();
}

AudioDevice DeviceEnumerator::get_default_output() {
    auto devices = list_audio_outputs();

    // Find default device
    auto it = std::find_if(devices.begin(), devices.end(),
                          [](const AudioDevice &dev) { return dev.is_default; });

    if (it != devices.end()) {
        return *it;
    }

    // Fallback: return first device or empty
    if (!devices.empty()) {
        std::cout << "[DeviceEnumerator] No default output found, using first device" << std::endl;
        return devices[0];
    }

    std::cerr << "[DeviceEnumerator] No output devices found!" << std::endl;
    return AudioDevice();
}

/**
 * Enumerate video devices
 */
std::vector<VideoDevice> DeviceEnumerator::enumerate_video_devices(const char *classes) {
    std::vector<VideoDevice> devices;

    try {
        std::cout << "[DeviceEnumerator] Enumerating video devices on " << OS_FAMILY << "..." << std::endl;

        // Create device monitor - but DON'T start/stop it
        GstDeviceMonitor *monitor = gst_device_monitor_new();
        if (!monitor) {
            std::cerr << "[DeviceEnumerator] Failed to create device monitor" << std::endl;
            return devices;
        }

        // Add filter for video sources
        gst_device_monitor_add_filter(monitor, classes, nullptr);

        // Get devices WITHOUT start/stop - avoids PipeWire double-free bug
        GList *device_list = gst_device_monitor_get_devices(monitor);

        for (GList *l = device_list; l != nullptr; l = l->next) {
            GstDevice *device = GST_DEVICE(l->data);

            VideoDevice video_dev;

            // Get device ID
            video_dev.id = extract_device_id(device);

            // Get display name
            gchar *display_name = gst_device_get_display_name(device);
            if (display_name) {
                video_dev.name = display_name;
                g_free(display_name);
            }

            // Get device class
            gchar *device_class = gst_device_get_device_class(device);
            if (device_class) {
                video_dev.description = device_class;
                g_free(device_class);
            }

            // Get device path (Linux: /dev/video0, etc.)
            GstStructure *props = gst_device_get_properties(device);
            if (props) {
                const gchar *path = gst_structure_get_string(props, "device.path");
                if (path) {
                    video_dev.device_path = path;
                }
                gst_structure_free(props);
            }

            // Check if default
            video_dev.is_default = is_default_device(device);

            std::cout << "[DeviceEnumerator]   " << (video_dev.is_default ? "✓ " : "  ")
                      << video_dev.name << " (id: " << video_dev.id;
            if (!video_dev.device_path.empty()) {
                std::cout << ", path: " << video_dev.device_path;
            }
            std::cout << ")" << std::endl;

            devices.push_back(video_dev);
            gst_object_unref(device);
        }

        g_list_free(device_list);

        // Cleanup - no start/stop needed, just unref
        gst_object_unref(monitor);

        std::cout << "[DeviceEnumerator] Found " << devices.size() << " video devices" << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "[DeviceEnumerator] Exception: " << e.what() << std::endl;
    }

    return devices;
}

std::vector<VideoDevice> DeviceEnumerator::list_video_sources() {
    return enumerate_video_devices(get_video_source_classes());
}

VideoDevice DeviceEnumerator::get_default_video_source() {
    auto devices = list_video_sources();

    // Find default device
    auto it = std::find_if(devices.begin(), devices.end(),
                          [](const VideoDevice &dev) { return dev.is_default; });

    if (it != devices.end()) {
        return *it;
    }

    // Fallback: return first device or empty
    if (!devices.empty()) {
        std::cout << "[DeviceEnumerator] No default video source found, using first device" << std::endl;
        return devices[0];
    }

    std::cerr << "[DeviceEnumerator] No video devices found!" << std::endl;
    return VideoDevice();
}

} // namespace drunk_call
