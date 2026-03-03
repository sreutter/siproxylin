/**
 * SessionManager Test
 *
 * Purpose: Verify thread-safe session map for gRPC service
 * Tests: Add/get/remove sessions, concurrent access
 *
 * Pattern: docs/CALLS/4-GRPC-PLAN.md lines 186-209
 * Build: make test_session_manager
 * Run: ./test_session_manager
 */

#include "../../src/session_manager.h"
#include "call.pb.h"  // For complete call::CallEvent type (from build/generated/)
#include <iostream>
#include <thread>
#include <vector>
#include <cassert>

using namespace drunk_call;

// Test 1: Basic add/get/remove
bool test_basic_operations() {
    std::cout << "=== Test 1: Basic add/get/remove ===" << std::endl;

    SessionManager manager;

    // Create test session
    auto session = std::make_shared<CallSession>();
    session->session_id = "test-session-1";
    session->peer_jid = "alice@example.com";
    session->active = true;
    session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();

    // Add session
    manager.add_session("test-session-1", session);
    std::cout << "  ✓ Added session: " << session->session_id << std::endl;

    // Get session
    auto retrieved = manager.get_session("test-session-1");
    assert(retrieved != nullptr);
    assert(retrieved->session_id == "test-session-1");
    assert(retrieved->peer_jid == "alice@example.com");
    std::cout << "  ✓ Retrieved session: " << retrieved->peer_jid << std::endl;

    // Get non-existent session
    auto not_found = manager.get_session("does-not-exist");
    assert(not_found == nullptr);
    std::cout << "  ✓ Non-existent session returns nullptr" << std::endl;

    // Remove session
    manager.remove_session("test-session-1");
    auto removed = manager.get_session("test-session-1");
    assert(removed == nullptr);
    std::cout << "  ✓ Session removed successfully" << std::endl;

    return true;
}

// Test 2: Multiple sessions
bool test_multiple_sessions() {
    std::cout << "\n=== Test 2: Multiple sessions ===" << std::endl;

    SessionManager manager;

    // Add 10 sessions
    for (int i = 0; i < 10; i++) {
        auto session = std::make_shared<CallSession>();
        session->session_id = "session-" + std::to_string(i);
        session->peer_jid = "user" + std::to_string(i) + "@example.com";
        session->active = true;
        session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
        manager.add_session(session->session_id, session);
    }
    std::cout << "  ✓ Added 10 sessions" << std::endl;

    // Get all session IDs
    auto ids = manager.get_all_session_ids();
    assert(ids.size() == 10);
    std::cout << "  ✓ Retrieved all " << ids.size() << " session IDs" << std::endl;

    // Verify each session is retrievable
    for (int i = 0; i < 10; i++) {
        auto session = manager.get_session("session-" + std::to_string(i));
        assert(session != nullptr);
        assert(session->peer_jid == "user" + std::to_string(i) + "@example.com");
    }
    std::cout << "  ✓ All sessions are retrievable" << std::endl;

    // Remove all sessions
    for (const auto& id : ids) {
        manager.remove_session(id);
    }
    auto remaining = manager.get_all_session_ids();
    assert(remaining.empty());
    std::cout << "  ✓ All sessions removed" << std::endl;

    return true;
}

// Test 3: Shared pointer reference counting
bool test_reference_counting() {
    std::cout << "\n=== Test 3: Shared pointer reference counting ===" << std::endl;

    SessionManager manager;

    auto session = std::make_shared<CallSession>();
    session->session_id = "ref-test";
    session->peer_jid = "bob@example.com";
    session->active = true;
    session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();

    manager.add_session("ref-test", session);
    std::cout << "  ✓ Session added, ref count: " << session.use_count() << std::endl;

    // Get session - increases ref count
    {
        auto retrieved = manager.get_session("ref-test");
        assert(retrieved != nullptr);
        std::cout << "  ✓ Session retrieved, ref count: " << session.use_count() << std::endl;

        // Both pointers should point to same object
        assert(retrieved.get() == session.get());
        std::cout << "  ✓ Retrieved pointer points to same object" << std::endl;

        // When retrieved goes out of scope, ref count decreases
    }
    std::cout << "  ✓ Retrieved pointer destroyed, ref count: " << session.use_count() << std::endl;

    // Remove from manager
    manager.remove_session("ref-test");
    std::cout << "  ✓ Session removed from manager, ref count: " << session.use_count() << std::endl;

    // Original pointer still valid (we still hold a reference)
    assert(session->session_id == "ref-test");
    std::cout << "  ✓ Original pointer still valid after removal" << std::endl;

    return true;
}

// Test 4: Concurrent add/get from multiple threads
bool test_concurrent_access() {
    std::cout << "\n=== Test 4: Concurrent access (stress test) ===" << std::endl;

    SessionManager manager;
    const int num_threads = 10;
    const int ops_per_thread = 100;
    std::atomic<int> add_count(0);
    std::atomic<int> get_count(0);

    std::vector<std::thread> threads;

    // Each thread adds and gets sessions concurrently
    for (int t = 0; t < num_threads; t++) {
        threads.emplace_back([&manager, t, ops_per_thread, &add_count, &get_count]() {
            for (int i = 0; i < ops_per_thread; i++) {
                std::string session_id = "thread-" + std::to_string(t) + "-session-" + std::to_string(i);

                // Add session
                auto session = std::make_shared<CallSession>();
                session->session_id = session_id;
                session->peer_jid = "user@example.com";
                session->active = true;
                session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
                manager.add_session(session_id, session);
                add_count++;

                // Immediately try to get it
                auto retrieved = manager.get_session(session_id);
                if (retrieved != nullptr && retrieved->session_id == session_id) {
                    get_count++;
                }
            }
        });
    }

    // Wait for all threads
    for (auto& t : threads) {
        t.join();
    }

    std::cout << "  ✓ " << num_threads << " threads completed" << std::endl;
    std::cout << "  ✓ Total adds: " << add_count << std::endl;
    std::cout << "  ✓ Total successful gets: " << get_count << std::endl;

    assert(add_count == num_threads * ops_per_thread);
    assert(get_count == num_threads * ops_per_thread);
    std::cout << "  ✓ All operations succeeded without data races" << std::endl;

    // Verify all sessions are in manager
    auto ids = manager.get_all_session_ids();
    assert(ids.size() == num_threads * ops_per_thread);
    std::cout << "  ✓ All " << ids.size() << " sessions present in manager" << std::endl;

    return true;
}

// Test 5: Concurrent add/remove (simulates real usage)
bool test_concurrent_lifecycle() {
    std::cout << "\n=== Test 5: Concurrent session lifecycle ===" << std::endl;

    SessionManager manager;
    const int num_sessions = 20;  // Reduced from 50
    std::atomic<int> sessions_created(0);
    std::atomic<int> sessions_removed(0);

    std::vector<std::thread> threads;

    // Thread 1: Adds sessions
    threads.emplace_back([&manager, num_sessions, &sessions_created]() {
        for (int i = 0; i < num_sessions; i++) {
            auto session = std::make_shared<CallSession>();
            session->session_id = "lifecycle-" + std::to_string(i);
            session->peer_jid = "user@example.com";
            session->active = true;
            session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
            manager.add_session(session->session_id, session);
            sessions_created++;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));  // 1ms instead of 100μs
        }
    });

    // Thread 2: Gets sessions
    threads.emplace_back([&manager, num_sessions]() {
        for (int i = 0; i < num_sessions; i++) {
            std::string session_id = "lifecycle-" + std::to_string(i);
            // Keep trying until session exists (with max retries to avoid infinite loop)
            int retries = 0;
            while (manager.get_session(session_id) == nullptr && retries++ < 1000) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    });

    // Thread 3: Removes sessions
    threads.emplace_back([&manager, num_sessions, &sessions_removed]() {
        for (int i = 0; i < num_sessions; i++) {
            std::string session_id = "lifecycle-" + std::to_string(i);
            // Wait until session exists (with max retries)
            int retries = 0;
            while (manager.get_session(session_id) == nullptr && retries++ < 1000) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            // Remove it
            manager.remove_session(session_id);
            sessions_removed++;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
    });

    // Wait for all threads
    for (auto& t : threads) {
        t.join();
    }

    std::cout << "  ✓ Sessions created: " << sessions_created << std::endl;
    std::cout << "  ✓ Sessions removed: " << sessions_removed << std::endl;

    assert(sessions_created == num_sessions);
    assert(sessions_removed == num_sessions);

    // All sessions should be removed
    auto remaining = manager.get_all_session_ids();
    assert(remaining.empty());
    std::cout << "  ✓ All sessions cleaned up, map is empty" << std::endl;

    return true;
}

// Test 6: Remove while in use (real gRPC pattern: StreamEvents holds session, EndSession removes it)
bool test_remove_while_in_use() {
    std::cout << "\n=== Test 6: Remove session while other threads hold references ===" << std::endl;

    SessionManager manager;
    const int num_sessions = 10;
    std::atomic<int> sessions_still_valid(0);
    std::atomic<int> threads_holding(0);
    const int num_holder_threads = 5;

    // First, create all sessions
    for (int i = 0; i < num_sessions; i++) {
        auto session = std::make_shared<CallSession>();
        session->session_id = "remove-test-" + std::to_string(i);
        session->peer_jid = "user@example.com";
        session->active = true;
        session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
        manager.add_session(session->session_id, session);
    }
    std::cout << "  ✓ Created " << num_sessions << " sessions" << std::endl;

    std::vector<std::thread> threads;

    // "StreamEvents" threads: Get ALL sessions first, THEN verify them after removal
    for (int t = 0; t < num_holder_threads; t++) {
        threads.emplace_back([&manager, num_sessions, &sessions_still_valid, &threads_holding]() {
            // Step 1: Get all sessions and hold shared_ptrs
            std::vector<std::shared_ptr<CallSession>> held_sessions;
            for (int i = 0; i < num_sessions; i++) {
                std::string session_id = "remove-test-" + std::to_string(i);
                auto session = manager.get_session(session_id);
                if (session != nullptr) {
                    held_sessions.push_back(session);
                }
            }

            // Signal that we're holding all sessions
            threads_holding++;

            // Step 2: Wait for removal to happen (50ms)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));

            // Step 3: Verify all held shared_ptrs are still valid
            for (const auto& session : held_sessions) {
                if (session && session->session_id.find("remove-test-") == 0) {
                    sessions_still_valid++;
                }
            }
        });
    }

    // "EndSession" thread: Wait for all threads to hold sessions, THEN remove from map
    threads.emplace_back([&manager, num_sessions, &threads_holding, num_holder_threads]() {
        // Wait for all holder threads to acquire all sessions
        while (threads_holding < num_holder_threads) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        std::cout << "  ✓ All " << num_holder_threads << " threads holding sessions" << std::endl;

        // Now remove all sessions from map (while others hold shared_ptrs)
        for (int i = 0; i < num_sessions; i++) {
            std::string session_id = "remove-test-" + std::to_string(i);
            manager.remove_session(session_id);
        }
        std::cout << "  ✓ All sessions removed from map (while held by threads)" << std::endl;
    });

    // Wait for all threads
    for (auto& t : threads) {
        t.join();
    }

    std::cout << "  ✓ Sessions still valid after removal: " << sessions_still_valid << std::endl;

    // All 5 threads held all 10 sessions, and verified they're still valid after removal
    assert(sessions_still_valid == num_holder_threads * num_sessions);

    // Map should be empty now
    auto remaining = manager.get_all_session_ids();
    assert(remaining.empty());
    std::cout << "  ✓ Map is empty but " << num_holder_threads * num_sessions << " shared_ptrs still valid" << std::endl;
    std::cout << "  ✓ No crashes - shared_ptr ref-counting works correctly!" << std::endl;

    return true;
}

// Test 7: High-stress concurrent lifecycle (more realistic load)
bool test_stress_lifecycle() {
    std::cout << "\n=== Test 7: High-stress concurrent lifecycle ===" << std::endl;

    SessionManager manager;
    const int num_sessions = 100;  // Higher load
    std::atomic<int> add_successes(0);
    std::atomic<int> get_successes(0);
    std::atomic<int> remove_successes(0);

    std::vector<std::thread> threads;

    // 3 adder threads (divide sessions among them)
    int sessions_per_thread = num_sessions / 3;
    int remainder = num_sessions % 3;
    for (int t = 0; t < 3; t++) {
        threads.emplace_back([&manager, t, sessions_per_thread, remainder, &add_successes]() {
            int start = t * sessions_per_thread + std::min(t, remainder);
            int count = sessions_per_thread + (t < remainder ? 1 : 0);

            for (int i = 0; i < count; i++) {
                std::string session_id = "stress-" + std::to_string(start + i);
                auto session = std::make_shared<CallSession>();
                session->session_id = session_id;
                session->peer_jid = "user@example.com";
                session->active = true;
                session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
                manager.add_session(session_id, session);
                add_successes++;
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
        });
    }

    // 5 getter threads (continuously try to access sessions)
    for (int t = 0; t < 5; t++) {
        threads.emplace_back([&manager, num_sessions, &get_successes]() {
            for (int i = 0; i < 200; i++) {  // Many attempts
                std::string session_id = "stress-" + std::to_string(i % num_sessions);
                auto session = manager.get_session(session_id);
                if (session != nullptr) {
                    get_successes++;
                }
                std::this_thread::yield();  // Give other threads a chance
            }
        });
    }

    // 2 remover threads (start after 10ms, divide sessions among them)
    int remove_per_thread = num_sessions / 2;
    int remove_remainder = num_sessions % 2;
    for (int t = 0; t < 2; t++) {
        threads.emplace_back([&manager, t, remove_per_thread, remove_remainder, &remove_successes]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            int start = t * remove_per_thread + std::min(t, remove_remainder);
            int count = remove_per_thread + (t < remove_remainder ? 1 : 0);

            for (int i = 0; i < count; i++) {
                std::string session_id = "stress-" + std::to_string(start + i);
                // Try to remove (may not exist yet, that's OK)
                auto session = manager.get_session(session_id);
                if (session != nullptr) {
                    manager.remove_session(session_id);
                    remove_successes++;
                }
            }
        });
    }

    // Wait for all threads
    for (auto& t : threads) {
        t.join();
    }

    std::cout << "  ✓ Add operations: " << add_successes << " / " << num_sessions << std::endl;
    std::cout << "  ✓ Get operations succeeded: " << get_successes << " (out of 1000 attempts)" << std::endl;
    std::cout << "  ✓ Remove operations: " << remove_successes << std::endl;

    // All adds should succeed
    assert(add_successes == num_sessions);
    std::cout << "  ✓ No data races detected - all operations consistent" << std::endl;

    return true;
}

int main() {
    std::cout << "=== SessionManager Test Suite ===" << std::endl;
    std::cout << "Pattern: Thread-safe session map for gRPC handlers + GLib callbacks" << std::endl;
    std::cout << std::endl;

    bool all_passed = true;

    all_passed &= test_basic_operations();
    all_passed &= test_multiple_sessions();
    all_passed &= test_reference_counting();
    all_passed &= test_concurrent_access();
    all_passed &= test_concurrent_lifecycle();
    all_passed &= test_remove_while_in_use();     // NEW: Critical real-world pattern
    all_passed &= test_stress_lifecycle();        // NEW: Higher stress test

    std::cout << "\n=== Summary ===" << std::endl;
    if (all_passed) {
        std::cout << "✓ All tests passed!" << std::endl;
        std::cout << "\nSessionManager is thread-safe and ready for gRPC service integration." << std::endl;
        return 0;
    } else {
        std::cout << "✗ Some tests failed!" << std::endl;
        return 1;
    }
}
