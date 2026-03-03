#include "session_manager.h"
#include <algorithm>

namespace drunk_call {

std::shared_ptr<CallSession> SessionManager::get_session(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = sessions_.find(session_id);
    if (it == sessions_.end()) {
        return nullptr;
    }
    return it->second;  // shared_ptr keeps session alive during use
}

void SessionManager::add_session(const std::string& session_id,
                                 std::shared_ptr<CallSession> session) {
    std::lock_guard<std::mutex> lock(mutex_);
    sessions_[session_id] = session;
}

void SessionManager::remove_session(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    sessions_.erase(session_id);
}

std::vector<std::string> SessionManager::get_all_session_ids() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> ids;
    ids.reserve(sessions_.size());
    for (const auto& pair : sessions_) {
        ids.push_back(pair.first);
    }
    return ids;
}

} // namespace drunk_call
