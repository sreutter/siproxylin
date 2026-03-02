/**
 * Logger Implementation
 */

#include "logger.h"
#include <spdlog/spdlog.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <algorithm>
#include <iostream>
#include <filesystem>

namespace drunk_call {

std::shared_ptr<spdlog::logger> Logger::logger_ = nullptr;

void Logger::init(const std::string &log_path, const std::string &log_level,
                  size_t max_file_size, size_t max_files) {
    try {
        // Create log directory if needed
        std::filesystem::path log_file_path(log_path);
        std::filesystem::path log_dir = log_file_path.parent_path();

        if (!log_dir.empty() && !std::filesystem::exists(log_dir)) {
            std::filesystem::create_directories(log_dir);
        }

        // Create rotating file sink
        // Rotates when file reaches max_file_size, keeps max_files
        auto file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(
            log_path, max_file_size, max_files);

        // Create logger
        logger_ = std::make_shared<spdlog::logger>("drunk_call", file_sink);

        // Set log level
        std::string level_upper = log_level;
        std::transform(level_upper.begin(), level_upper.end(), level_upper.begin(), ::toupper);

        if (level_upper == "TRACE") {
            logger_->set_level(spdlog::level::trace);
        } else if (level_upper == "DEBUG") {
            logger_->set_level(spdlog::level::debug);
        } else if (level_upper == "INFO") {
            logger_->set_level(spdlog::level::info);
        } else if (level_upper == "WARN" || level_upper == "WARNING") {
            logger_->set_level(spdlog::level::warn);
        } else if (level_upper == "ERROR") {
            logger_->set_level(spdlog::level::err);
        } else if (level_upper == "CRITICAL") {
            logger_->set_level(spdlog::level::critical);
        } else {
            logger_->set_level(spdlog::level::info);
            logger_->warn("Unknown log level '{}', defaulting to INFO", log_level);
        }

        // Set pattern: [timestamp] [level] message
        logger_->set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%^%l%$] %v");

        // Flush on every log (ensures logs are written even if service crashes)
        logger_->flush_on(spdlog::level::trace);

        logger_->info("Logger initialized: path={}, level={}", log_path, level_upper);

    } catch (const std::exception &e) {
        // Fallback to stderr if file logger fails
        std::cerr << "[Logger] Failed to initialize: " << e.what() << std::endl;
        logger_ = spdlog::default_logger();
    }
}

std::shared_ptr<spdlog::logger> Logger::get() {
    if (!logger_) {
        // Lazy initialization with default logger if init() not called
        logger_ = spdlog::default_logger();
    }
    return logger_;
}

void Logger::shutdown() {
    if (logger_) {
        logger_->info("Logger shutting down");
        logger_->flush();
        spdlog::shutdown();
    }
}

} // namespace drunk_call
