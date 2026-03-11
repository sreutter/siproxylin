# Video Viewer Implementation Plan

**Status**: Planning
**Created**: 2026-03-11
**Based On**: Image viewer implementation (commit `4315d951837ff2`)

## Overview

This document outlines the plan for implementing a video viewer dialog using python-vlc, following the same integration patterns as the image viewer.

## Architecture Analysis

### Image Viewer Pattern (Reference)

The image viewer implementation provides our template:

1. **Self-contained dialog** (`image_viewer_dialog.py`) - 357 lines with zoom controls
2. **Click handler** in `messages.py` - Detects image clicks and opens viewer
3. **Context menu** in `context_menus.py` - Right-click "Open Image" option
4. **Shared utilities** in `file_utils.py` - "Save As" and "Open With" for all file types
5. **MIME detection** - Uses `mime_type.startswith('image/')` pattern

Key files:
- `siproxylin/gui/dialogs/image_viewer_dialog.py` - Main dialog implementation
- `siproxylin/gui/chat_view/taps/messages.py` - Click handlers
- `siproxylin/gui/chat_view/taps/context_menus.py` - Context menu integration
- `siproxylin/utils/file_utils.py` - Shared file operations

## Implementation Plan

### Phase 1: Dependencies and Setup

#### 1.1 System Dependencies

**Required packages**:
- **python-vlc**: Python bindings for libVLC
  - Installation: `pip install python-vlc`
  - License: LGPL-2.1+ (compatible with AGPL-3.0)

- **libvlc**: VLC media player libraries
  - Debian/Ubuntu: `apt install libvlc-dev vlc`
  - Arch Linux: `pacman -S vlc`
  - macOS: `brew install vlc`
  - Windows: Bundled with VLC installer
  - License: LGPL-2.1+ (compatible with AGPL-3.0)

#### 1.2 Verification Test

Before implementation, verify VLC availability:

```python
try:
    import vlc
    instance = vlc.Instance()
    if instance:
        print("VLC available")
        instance.release()
except ImportError:
    print("python-vlc not installed")
except Exception as e:
    print(f"VLC initialization error: {e}")
```

### Phase 2: Video Viewer Dialog

#### 2.1 Create Dialog File

**Location**: `siproxylin/gui/dialogs/video_viewer_dialog.py`

**Estimated size**: ~400-500 lines (similar to image viewer)

#### 2.2 Dialog Architecture

```
VideoViewerDialog(QDialog)
├── VLC Video Widget (QFrame for platform-native playback)
├── Control Bar (QHBoxLayout)
│   ├── Play/Pause Button (toggle icon/text)
│   ├── Position Slider (seek bar, 0-1000 range)
│   ├── Time Labels (current/total in MM:SS format)
│   ├── Volume Slider (0-100)
│   ├── Fullscreen Button
│   └── Spacer
└── Button Bar (QHBoxLayout)
    ├── Save As... (reuse file_utils.save_file_as)
    ├── Open With... (reuse file_utils.open_file_with_external_app)
    ├── Spacer
    └── Close
```

#### 2.3 Key Components

**VLC Integration**:
```python
self.vlc_instance = vlc.Instance()
self.media_player = self.vlc_instance.media_player_new()

# Platform-specific video output
if sys.platform.startswith('linux'):
    self.media_player.set_xwindow(self.video_widget.winId())
elif sys.platform == 'win32':
    self.media_player.set_hwnd(self.video_widget.winId())
elif sys.platform == 'darwin':
    self.media_player.set_nsobject(int(self.video_widget.winId()))
```

**Video Surface Widget**:
- Use `QFrame` with black background
- Minimum size: 800x600
- Handle resize events for aspect ratio

**Playback Controls**:
- **Play/Pause**: Toggle button (updates icon/text based on state)
- **Seek Slider**: QSlider for position (0-1000 range for precision)
- **Time Display**: "MM:SS / MM:SS" format
- **Volume Slider**: QSlider (0-100), syncs with VLC volume
- **Fullscreen**: Toggle fullscreen mode

**Event Handling**:
- **Position Updates**: QTimer polling `media_player.get_position()` every 100ms
- **End Detection**: Check `media_player.get_state() == vlc.State.Ended`
- **Keyboard Shortcuts**:
  - Space: Play/Pause
  - Left/Right Arrow: Seek ±5 seconds
  - Up/Down Arrow: Volume ±5%
  - F: Toggle fullscreen
  - Escape: Exit fullscreen or close dialog

#### 2.4 Class Structure

```python
class VideoViewerDialog(QDialog):
    """Dialog for viewing video files with playback controls."""

    def __init__(self, video_path, parent=None):
        """
        Initialize video viewer dialog.

        Args:
            video_path: Path to video file
            parent: Parent widget
        """
        super().__init__(parent)

        self.video_path = video_path
        self.vlc_instance = None
        self.media_player = None
        self.is_playing = False
        self.is_fullscreen = False
        self.position_timer = None

        self._setup_ui()
        self._setup_vlc()
        self._load_video()

    def _setup_ui(self):
        """Setup dialog UI components."""
        # Create video widget, controls, buttons

    def _setup_vlc(self):
        """Initialize VLC instance and media player."""

    def _load_video(self):
        """Load video file into player."""

    def _play_pause(self):
        """Toggle playback state."""

    def _update_position(self):
        """Timer callback to update slider and time display."""

    def _seek(self, position):
        """Seek to position (0.0-1.0)."""

    def _set_volume(self, volume):
        """Set volume (0-100)."""

    def _toggle_fullscreen(self):
        """Enter or exit fullscreen mode."""

    def _save_video(self):
        """Save video to user-selected location."""
        from ...utils import save_file_as
        save_file_as(self.video_path, parent_widget=self)

    def _open_with_external(self):
        """Open video with external application."""
        from ...utils import open_file_with_external_app
        open_file_with_external_app(self.video_path, parent_widget=self)

    def closeEvent(self, event):
        """Handle dialog close - CRITICAL: Release VLC resources."""
        if self.position_timer:
            self.position_timer.stop()

        if self.media_player:
            self.media_player.stop()
            self.media_player.release()

        if self.vlc_instance:
            self.vlc_instance.release()

        super().closeEvent(event)

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        # Space, arrows, F, Escape
```

#### 2.5 Performance Considerations

- **Streaming**: VLC handles file streaming automatically (no memory issues with large files)
- **Hardware Acceleration**: Enabled by default in VLC
- **Position Updates**: 100ms polling interval balances responsiveness and performance
- **Resource Cleanup**: Always release player and instance in `closeEvent()`

### Phase 3: MIME Type Detection

#### 3.1 Supported Video Formats

Common video MIME types:
- `video/mp4` (.mp4, .m4v)
- `video/webm` (.webm)
- `video/x-matroska` (.mkv)
- `video/x-msvideo` (.avi)
- `video/quicktime` (.mov)
- `video/x-flv` (.flv)
- `video/ogg` (.ogv)
- `video/3gpp` (.3gp)

#### 3.2 Detection Pattern

Following image viewer pattern:

```python
mime_type = index.data(MessageBubbleDelegate.ROLE_MIME_TYPE)
is_video = mime_type and mime_type.startswith('video/')
```

Fallback using mimetypes module:
```python
import mimetypes
mime_type, _ = mimetypes.guess_type(file_path)
```

### Phase 4: Message Click Integration

#### 4.1 Modify `messages.py`

**File**: `siproxylin/gui/chat_view/taps/messages.py`

**Location**: In `_on_message_clicked` method (around line 1184)

**Add after image handling block**:

```python
# Handle video files
elif file_path and mime_type and mime_type.startswith('video/'):
    from pathlib import Path

    if Path(file_path).exists():
        logger.info(f"Opening video viewer for: {file_path}")

        from ...dialogs import VideoViewerDialog
        dialog = VideoViewerDialog(file_path, self.parent)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()
    else:
        logger.warning(f"Video file not found: {file_path}")
```

**Note**: Use `elif` to ensure each file is handled only once.

#### 4.2 Cursor Change for Videos

**File**: `siproxylin/gui/chat_view/taps/messages.py`

**Location**: In `eventFilter` method (around line 1222)

**Current code** (for images only):
```python
if mime_type and mime_type.startswith('image/') and file_path:
    self.message_area.viewport().setCursor(QCursor(Qt.PointingHandCursor))
```

**Modify to include videos**:
```python
if mime_type and (mime_type.startswith('image/') or mime_type.startswith('video/')) and file_path:
    self.message_area.viewport().setCursor(QCursor(Qt.PointingHandCursor))
```

### Phase 5: Context Menu Integration

#### 5.1 Modify `context_menus.py`

**File**: `siproxylin/gui/chat_view/taps/context_menus.py`

**Location**: In `show_message_context_menu` method (after image block, around line 143)

**Add video handling**:

```python
# For video attachments: add Open Video option
elif mime_type and mime_type.startswith('video/'):
    from pathlib import Path

    if Path(file_path).exists():
        menu.addSeparator()

        open_action = QAction("Open Video", self.parent)
        open_action.triggered.connect(lambda: self._open_video_viewer(file_path))
        menu.addAction(open_action)

        open_with_action = QAction("Open With...", self.parent)
        open_with_action.triggered.connect(lambda: self._open_with_external(file_path, mime_type))
        menu.addAction(open_with_action)
```

**Add helper method**:

```python
def _open_video_viewer(self, video_path):
    """Open video in viewer dialog."""
    from PySide6.QtCore import Qt
    from ...dialogs import VideoViewerDialog
    dialog = VideoViewerDialog(video_path, self.parent)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.show()
```

**Note**: "Save As..." and "Properties" already work for all files (no changes needed).

### Phase 6: Dialog Export

#### 6.1 Update `dialogs/__init__.py`

**File**: `siproxylin/gui/dialogs/__init__.py`

**Add import**:
```python
from .video_viewer_dialog import VideoViewerDialog
```

**Update `__all__`**:
```python
__all__ = [
    'IncomingCallDialog',
    'OutgoingCallDialog',
    'InviteContactDialog',
    'SelectMucDialog',
    'ImageViewerDialog',
    'VideoViewerDialog'
]
```

### Phase 7: File Utilities

**No changes needed** - Existing utilities already handle all file types:
- `file_utils.save_file_as()` - Generic file save dialog
- `file_utils.open_file_with_external_app()` - MIME-type aware app chooser

### Phase 8: Error Handling

#### 8.1 VLC Not Available

**In `VideoViewerDialog.__init__`**:

```python
try:
    import vlc
    self.vlc_instance = vlc.Instance()
except ImportError:
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(
        self,
        "VLC Not Available",
        "python-vlc is not installed.\n\n"
        "Install with: pip install python-vlc"
    )
    self.reject()
    return
except Exception as e:
    logger.error(f"VLC initialization failed: {e}")
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(
        self,
        "VLC Error",
        f"Failed to initialize VLC: {e}\n\n"
        "Try opening with external application instead."
    )
    self.reject()
    return
```

#### 8.2 Video Load Failures

```python
def _load_video(self):
    """Load video file into player."""
    if not self.media_player:
        return

    from pathlib import Path
    if not Path(self.video_path).exists():
        logger.error(f"Video file not found: {self.video_path}")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self,
            "File Not Found",
            f"Video file not found:\n{self.video_path}"
        )
        return

    media = self.vlc_instance.media_new(self.video_path)
    if not media:
        logger.error(f"Failed to create media for {self.video_path}")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(
            self,
            "Video Load Error",
            f"Failed to load video:\n{self.video_path}"
        )
        return

    self.media_player.set_media(media)
    media.release()  # Player keeps reference
```

#### 8.3 Edge Cases

- **Large files**: VLC streams automatically (no memory issues)
- **Unsupported codecs**: VLC has broad support; fallback to "Open With" available
- **Multiple viewers**: Use `WA_DeleteOnClose` for proper cleanup
- **Closing during playback**: Stop player in `closeEvent()`

### Phase 9: Architectural Compliance

#### 9.1 Design Principles

**Modularity** ✓
- Self-contained dialog (no GUI logic in core layer)
- Reuses existing file utilities
- Independent of XMPP/barrels layer

**Single Responsibility** ✓
- `VideoViewerDialog`: Video playback only
- Click handler in `messages.py`: Detection and launching
- Context menu in `context_menus.py`: Menu integration

**Library-Based** ✓
- Uses mature python-vlc library
- No manual codec handling
- Platform-native file operations

**Privacy First** ✓
- No network access (local playback only)
- No telemetry or external calls
- File encryption handled upstream by XMPP transfer

#### 9.2 Code Quality Rules (from ADR)

- **Use logger** ✓ - No `print()` statements
- **Error handling** ✓ - Try/except with traceback logging
- **Resource cleanup** ✓ - Release VLC in `closeEvent()`
- **Qt best practices** ✓ - Use `WA_DeleteOnClose`, signals/slots
- **No blocking** ✓ - Async where needed, timer for updates

### Phase 10: Testing Strategy

#### 10.1 Manual Testing Checklist

**Basic Playback**:
- [ ] Click video in chat opens viewer
- [ ] Play/pause button works
- [ ] Seek slider functional
- [ ] Volume control works
- [ ] Fullscreen toggle works
- [ ] Time display updates correctly

**Edge Cases**:
- [ ] Missing file shows error dialog
- [ ] Corrupted file handled gracefully
- [ ] Very large file (>1GB) streams smoothly
- [ ] Multiple videos open simultaneously
- [ ] Closing during playback doesn't crash
- [ ] VLC not installed shows helpful error

**Integration**:
- [ ] Right-click "Open Video" works
- [ ] "Save As..." works for videos
- [ ] "Open With..." works for videos
- [ ] Cursor changes to pointer on hover
- [ ] Dialog closes properly with ESC/close button
- [ ] Keyboard shortcuts work (space, arrows, F, escape)

**Cross-Platform**:
- [ ] Linux (X11 and Wayland)
- [ ] Windows
- [ ] macOS

**File Formats**:
- [ ] MP4
- [ ] WebM
- [ ] MKV
- [ ] AVI
- [ ] MOV
- [ ] FLV
- [ ] OGV

#### 10.2 Regression Testing

- [ ] Image viewer still works (no conflicts)
- [ ] File properties dialog works for videos
- [ ] Context menu layout correct for both images and videos
- [ ] Clicking non-media files doesn't trigger viewers

### Phase 11: Documentation

#### 11.1 Files to Update

**README.md**:
- Add python-vlc to Python dependencies
- Add libvlc to system dependencies

**docs/ARCHITECTURE.md** (if it lists dialogs):
- Add VideoViewerDialog to dialog list

#### 11.2 Code Comments

Follow existing pattern from image viewer:

```python
"""
Video viewer dialog for displaying video files with playback controls.

Features:
- Video playback using VLC media player
- Playback controls (play/pause, seek, volume)
- Fullscreen mode
- Keyboard shortcuts
- Save As and Open With integration

Requires:
- python-vlc: Python bindings for libVLC
- libvlc: VLC media player libraries
"""
```

## Implementation Order

**Follow ADR session workflow**: "1 task → user test → remind commit → update docs → move on"

**Recommended sequence**:

1. **Verify VLC** - Test python-vlc availability
   - Create simple test script
   - Verify VLC can play sample video

2. **Implement VideoViewerDialog** - Core functionality
   - Create dialog file with basic UI
   - Implement VLC integration
   - Add playback controls
   - **User test** with sample video

3. **Add click handler** - Integration with messages.py
   - Detect video clicks
   - Launch viewer dialog
   - **User test** clicking videos in chat

4. **Add context menu** - Right-click integration
   - Add "Open Video" option
   - Add "Open With..." option
   - **User test** context menu

5. **Add error handling** - Edge cases
   - VLC not available
   - File not found
   - Load failures
   - **User test** error scenarios

6. **Final testing** - Comprehensive test
   - All file formats
   - All platforms (if applicable)
   - Regression testing
   - **User test** complete feature

7. **Commit** - User commits the feature
   - Remind user to commit
   - Verify commit message follows repo style

8. **Update documentation** - README and docs
   - Add dependencies
   - Update architecture docs if needed

9. **Commit** - User commits documentation
   - Remind user to commit docs separately

## Key Differences from Image Viewer

| Aspect | Image Viewer | Video Viewer |
|--------|--------------|--------------|
| **Library** | Qt's QPixmap (built-in) | python-vlc (external) |
| **Main Widget** | QLabel with pixmap | QFrame (VLC surface) |
| **Controls** | Zoom buttons (in/out/fit/actual) | Playback controls (play/pause/seek/volume) |
| **State** | Static (zoom level) | Dynamic (playing, position, time) |
| **Keyboard** | Zoom shortcuts (Ctrl+/-/0) | Media shortcuts (space, arrows, F) |
| **Resource Cleanup** | Automatic (Qt handles) | Manual (must release VLC) |
| **Performance** | Memory-bound (entire image) | CPU/GPU-bound (streaming) |
| **Fullscreen** | Nice to have | Essential feature |
| **Updates** | One-time display | Continuous (position timer) |

## Future Enhancements

**Not in initial implementation** (keep scope limited):

- Playback speed control (0.5x, 1.0x, 1.5x, 2.0x)
- Subtitle support (SRT, VTT files)
- Audio track selection (multi-language)
- Video filters/effects
- Playlist support (multiple videos)
- Thumbnail preview in chat (requires video processing)
- Video format conversion
- Screenshot capture from video
- Frame-by-frame navigation

**Follow ADR**: "Quality > Speed" - Get basic viewer working perfectly first, then consider enhancements.

## Summary

This implementation plan mirrors the image viewer while adapting to video-specific requirements:

1. **Self-contained dialog** with VLC integration (~400-500 lines)
2. **Click detection** in message widget (pattern: `mime_type.startswith('video/')`)
3. **Context menu** integration ("Open Video", "Open With...")
4. **Reuses file utilities** (save, open with) - no duplication
5. **Proper error handling** and resource cleanup
6. **Follows architecture principles** and ADR code quality rules

The implementation maintains consistency with existing code style, integration patterns, and architectural decisions while providing a robust video viewing experience.

---

**Last Updated**: 2026-03-11
**Status**: Ready for implementation
