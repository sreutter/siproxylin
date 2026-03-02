/**
 * Logger Wrapper (spdlog)
 *
 * Usage:
 * - Call Logger::init(log_path, log_level) at startup
 * - Use LOG_*() macros throughout code
 * - User-defined logs go to file
 * - STDOUT reserved for libnice/GStreamer debug
 * - STDERR reserved for unhandled exceptions
 *
 * Log levels: TRACE, DEBUG, INFO, WARN, ERROR, CRITICAL
 *
 * Example:
 *   Logger::init("~/.siproxylin/logs/drunk-call-service.log", "DEBUG");
 *   LOG_INFO("Service starting");
 *   LOG_DEBUG("Session created: {}", session_id);
 *   LOG_ERROR("Failed to connect: {}", error);
 */

#ifndef LOGGER_H
#define LOGGER_H

#include <spdlog/spdlog.h>
#include <spdlog/sinks/basic_file_sink.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <memory>
#include <string>

namespace drunk_call {

class Logger {
public:
    /**
     * Initialize logger
     * @param log_path Path to log file (e.g., ~/.siproxylin/logs/drunk-call-service.log)
     * @param log_level Log level: "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"
     * @param max_file_size Maximum log file size in bytes (default: 10MB)
     * @param max_files Maximum number of rotated files (default: 3)
     */
    static void init(const std::string &log_path,
                     const std::string &log_level = "INFO",
                     size_t max_file_size = 1024 * 1024 * 10,
                     size_t max_files = 3);

    /**
     * Get logger instance
     */
    static std::shared_ptr<spdlog::logger> get();

    /**
     * Shutdown logger (call at exit)
     */
    static void shutdown();

private:
    static std::shared_ptr<spdlog::logger> logger_;
};

// Convenience macros
#define LOG_TRACE(...) drunk_call::Logger::get()->trace(__VA_ARGS__)
#define LOG_DEBUG(...) drunk_call::Logger::get()->debug(__VA_ARGS__)
#define LOG_INFO(...)  drunk_call::Logger::get()->info(__VA_ARGS__)
#define LOG_WARN(...)  drunk_call::Logger::get()->warn(__VA_ARGS__)
#define LOG_ERROR(...) drunk_call::Logger::get()->error(__VA_ARGS__)
#define LOG_CRITICAL(...) drunk_call::Logger::get()->critical(__VA_ARGS__)

} // namespace drunk_call

#endif // LOGGER_H
