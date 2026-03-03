/**
 * ThreadSafeQueue Test
 *
 * Purpose: Verify thread-safe queue for GLib → gRPC event streaming
 * Tests: Basic push/pop, timeout, shutdown, concurrent access
 *
 * Pattern: docs/CALLS/GSTREAMER-THREADING.md lines 273-316
 * Build: make test_thread_safe_queue
 * Run: ./test_thread_safe_queue
 */

#include "../../src/thread_safe_queue.h"
#include <iostream>
#include <thread>
#include <vector>
#include <atomic>
#include <cassert>

// Test data structure
struct TestEvent {
    int id;
    std::string message;

    TestEvent() : id(0) {}
    TestEvent(int i, const std::string& msg) : id(i), message(msg) {}
};

// Test 1: Basic push/pop
bool test_basic_push_pop() {
    std::cout << "=== Test 1: Basic push/pop ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;

    // Push 3 events
    queue.push(TestEvent(1, "first"));
    queue.push(TestEvent(2, "second"));
    queue.push(TestEvent(3, "third"));

    // Pop 3 events
    TestEvent event;
    assert(queue.pop(event, std::chrono::milliseconds(100)));
    assert(event.id == 1 && event.message == "first");
    std::cout << "  ✓ Popped: " << event.id << " - " << event.message << std::endl;

    assert(queue.pop(event, std::chrono::milliseconds(100)));
    assert(event.id == 2 && event.message == "second");
    std::cout << "  ✓ Popped: " << event.id << " - " << event.message << std::endl;

    assert(queue.pop(event, std::chrono::milliseconds(100)));
    assert(event.id == 3 && event.message == "third");
    std::cout << "  ✓ Popped: " << event.id << " - " << event.message << std::endl;

    std::cout << "  ✓ All events popped in FIFO order" << std::endl;
    return true;
}

// Test 2: Timeout behavior
bool test_timeout() {
    std::cout << "\n=== Test 2: Timeout behavior ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;
    TestEvent event;

    auto start = std::chrono::steady_clock::now();
    bool result = queue.pop(event, std::chrono::milliseconds(500));
    auto elapsed = std::chrono::steady_clock::now() - start;

    assert(!result);  // Should timeout (queue empty)
    assert(elapsed >= std::chrono::milliseconds(450));  // Allow some slack
    std::cout << "  ✓ Timeout after " << std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count() << "ms" << std::endl;

    return true;
}

// Test 3: Blocking pop with producer
bool test_blocking_pop() {
    std::cout << "\n=== Test 3: Blocking pop (producer wakes consumer) ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;
    std::atomic<bool> consumer_woke(false);

    // Consumer thread: blocks waiting for event
    std::thread consumer([&queue, &consumer_woke]() {
        TestEvent event;
        bool success = queue.pop(event, std::chrono::milliseconds(5000));
        if (success && event.id == 42) {
            consumer_woke = true;
            std::cout << "  ✓ Consumer woke with event: " << event.message << std::endl;
        }
    });

    // Producer thread: waits 200ms, then pushes event
    std::thread producer([&queue]() {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        queue.push(TestEvent(42, "wake up!"));
        std::cout << "  ✓ Producer pushed event after 200ms" << std::endl;
    });

    consumer.join();
    producer.join();

    assert(consumer_woke);
    std::cout << "  ✓ Consumer successfully woke on push" << std::endl;

    return true;
}

// Test 4: Shutdown wakes all waiters
bool test_shutdown() {
    std::cout << "\n=== Test 4: Shutdown wakes all blocked threads ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;
    std::atomic<int> woken_count(0);

    // Start 3 consumer threads, all blocking
    std::vector<std::thread> consumers;
    for (int i = 0; i < 3; i++) {
        consumers.emplace_back([&queue, &woken_count]() {
            TestEvent event;
            bool result = queue.pop(event, std::chrono::milliseconds(5000));
            if (!result) {
                woken_count++;
            }
        });
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    std::cout << "  ✓ Started 3 blocking consumers" << std::endl;

    // Shutdown queue - should wake all consumers
    queue.shutdown();
    std::cout << "  ✓ Called shutdown()" << std::endl;

    for (auto& t : consumers) {
        t.join();
    }

    assert(woken_count == 3);
    std::cout << "  ✓ All 3 consumers woken by shutdown" << std::endl;

    return true;
}

// Test 5: Multiple producers, single consumer (stress test)
bool test_concurrent_producers() {
    std::cout << "\n=== Test 5: Multiple producers, single consumer ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;
    const int num_producers = 5;
    const int events_per_producer = 100;
    std::atomic<int> total_consumed(0);

    // Consumer thread
    std::thread consumer([&queue, &total_consumed]() {
        TestEvent event;
        while (total_consumed < num_producers * events_per_producer) {
            if (queue.pop(event, std::chrono::milliseconds(1000))) {
                total_consumed++;
            }
        }
    });

    // Producer threads
    std::vector<std::thread> producers;
    for (int i = 0; i < num_producers; i++) {
        producers.emplace_back([&queue, i, events_per_producer]() {
            for (int j = 0; j < events_per_producer; j++) {
                queue.push(TestEvent(i * 1000 + j, "producer " + std::to_string(i)));
            }
        });
    }

    // Wait for all producers
    for (auto& t : producers) {
        t.join();
    }
    std::cout << "  ✓ " << num_producers << " producers pushed " << events_per_producer << " events each" << std::endl;

    // Wait for consumer
    consumer.join();

    assert(total_consumed == num_producers * events_per_producer);
    std::cout << "  ✓ Consumer received all " << total_consumed << " events" << std::endl;

    return true;
}

// Test 6: Push after shutdown (should be no-op)
bool test_push_after_shutdown() {
    std::cout << "\n=== Test 6: Push after shutdown ===" << std::endl;

    ThreadSafeQueue<TestEvent> queue;
    queue.push(TestEvent(1, "before shutdown"));

    queue.shutdown();
    std::cout << "  ✓ Queue shutdown" << std::endl;

    // Push after shutdown - should not crash
    queue.push(TestEvent(2, "after shutdown"));
    std::cout << "  ✓ Push after shutdown did not crash" << std::endl;

    // Try to pop
    TestEvent event;
    bool result = queue.pop(event, std::chrono::milliseconds(100));

    // Should get the event pushed before shutdown
    if (result && event.id == 1) {
        std::cout << "  ✓ Got event from before shutdown: " << event.message << std::endl;
    }

    // Next pop should fail (queue empty and shutdown)
    result = queue.pop(event, std::chrono::milliseconds(100));
    assert(!result);
    std::cout << "  ✓ Subsequent pop failed (empty + shutdown)" << std::endl;

    return true;
}

int main() {
    std::cout << "=== ThreadSafeQueue Test Suite ===" << std::endl;
    std::cout << "Pattern: GLib thread → event queue → gRPC StreamEvents thread" << std::endl;
    std::cout << std::endl;

    bool all_passed = true;

    all_passed &= test_basic_push_pop();
    all_passed &= test_timeout();
    all_passed &= test_blocking_pop();
    all_passed &= test_shutdown();
    all_passed &= test_concurrent_producers();
    all_passed &= test_push_after_shutdown();

    std::cout << "\n=== Summary ===" << std::endl;
    if (all_passed) {
        std::cout << "✓ All tests passed!" << std::endl;
        return 0;
    } else {
        std::cout << "✗ Some tests failed!" << std::endl;
        return 1;
    }
}
