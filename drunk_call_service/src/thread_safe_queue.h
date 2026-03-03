#ifndef THREAD_SAFE_QUEUE_H
#define THREAD_SAFE_QUEUE_H

#include <queue>
#include <mutex>
#include <condition_variable>
#include <chrono>

/**
 * Thread-safe queue for cross-thread event communication.
 *
 * Used for GLib thread → gRPC thread event streaming.
 * Pattern verified in docs/CALLS/GSTREAMER-THREADING.md
 */
template<typename T>
class ThreadSafeQueue {
private:
    std::queue<T> queue_;
    std::mutex mutex_;
    std::condition_variable cv_;
    bool shutdown_ = false;

public:
    /**
     * Push item to queue (thread-safe).
     * Called from GLib thread (GStreamer callbacks).
     *
     * Note: Pushing after shutdown is a no-op (events discarded).
     */
    void push(const T& item) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (shutdown_) {
            return;  // Don't accept new items after shutdown
        }
        queue_.push(item);
        cv_.notify_one();  // Wake waiting thread
    }

    /**
     * Pop item from queue with timeout (thread-safe).
     * Called from gRPC StreamEvents thread.
     *
     * @param item Output parameter to store popped item
     * @param timeout How long to wait for an item
     * @return true if item was popped, false on timeout or shutdown
     */
    bool pop(T& item, std::chrono::milliseconds timeout = std::chrono::milliseconds(1000)) {
        std::unique_lock<std::mutex> lock(mutex_);

        // Wait for item or shutdown
        if (!cv_.wait_for(lock, timeout, [this] {
            return !queue_.empty() || shutdown_;
        })) {
            return false;  // Timeout
        }

        if (shutdown_ && queue_.empty()) {
            return false;  // Shutting down
        }

        item = std::move(queue_.front());
        queue_.pop();
        return true;
    }

    /**
     * Shutdown queue - wakes all waiting threads.
     * Called when session ends or service shuts down.
     */
    void shutdown() {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_ = true;
        cv_.notify_all();
    }

    /**
     * Check if queue is shutdown.
     */
    bool is_shutdown() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return shutdown_;
    }
};

#endif // THREAD_SAFE_QUEUE_H
