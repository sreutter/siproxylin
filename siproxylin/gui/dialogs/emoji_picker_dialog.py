"""
Emoji picker dialog - Pure UI component.

Shows a grid of emoji for the user to select.
Returns the selected emoji string (or None if cancelled).
"""

import logging
from typing import Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel,
    QDialogButtonBox, QPushButton, QLineEdit, QScrollArea, QWidget, QHBoxLayout
)
from PySide6.QtCore import Qt


logger = logging.getLogger('siproxylin.emoji_picker')


# Emoji metadata: (emoji, keywords, text_representations)
EMOJI_DATA = [
    # Faces - Happy
    ("😀", ["grinning", "smile", "happy"], [":D", ":-D"]),
    ("😃", ["smile", "happy", "joy"], [":)", ":-)"]),
    ("😄", ["smile", "happy", "laugh"], []),
    ("😁", ["grin", "happy"], []),
    ("😆", ["laugh", "satisfied", "happy"], []),
    ("😅", ["laugh", "nervous", "sweat"], []),
    ("🤣", ["rofl", "laugh", "rolling"], [":rofl:"]),
    ("😂", ["tears", "laugh", "joy"], []),
    ("😊", ["blush", "smile", "happy"], ["^^", "^_^"]),
    ("😇", ["angel", "innocent", "halo"], ["O:)", "O:-)"]),
    ("🙂", ["smile", "happy"], []),
    ("🙃", ["upside", "silly"], []),
    ("😉", ["wink", "flirt"], [";)", ";-)"]),
    ("😌", ["relieved", "calm"], []),
    ("😍", ["love", "heart", "eyes"], []),
    ("🥰", ["love", "hearts", "happy"], []),
    ("😘", ["kiss", "love"], [":*", ":-*"]),
    ("😗", ["kiss", "whistle"], []),
    ("😙", ["kiss", "smile"], []),
    ("😚", ["kiss", "closed", "eyes"], []),
    ("😋", ["yum", "delicious", "tongue"], []),
    ("😛", ["tongue", "playful"], [":P", ":-P"]),
    ("😝", ["tongue", "wink", "playful"], []),
    ("😜", ["tongue", "wink"], [";P", ";-P"]),
    ("🤪", ["crazy", "wild", "goofy"], []),
    ("🤨", ["raised", "eyebrow", "skeptical"], []),
    ("🧐", ["monocle", "thinking"], []),
    ("🤓", ["nerd", "geek", "glasses"], []),
    ("😎", ["cool", "sunglasses"], ["8)", "8-)", "B)", "B-)"]),
    ("🤩", ["star", "eyes", "excited"], []),
    ("🥳", ["party", "celebrate"], []),
    ("😏", ["smirk", "sly"], [":smirk:"]),

    # Faces - Neutral/Sad
    ("😒", ["unamused", "annoyed"], []),
    ("😞", ["disappointed", "sad"], []),
    ("😔", ["pensive", "sad"], []),
    ("😟", ["worried", "sad"], []),
    ("😕", ["confused", "uncertain"], []),
    ("🙁", ["frown", "sad"], []),
    ("😣", ["persevere", "struggle"], []),
    ("😖", ["confounded", "frustrated"], []),
    ("😫", ["tired", "exhausted"], []),
    ("😩", ["weary", "tired"], []),
    ("🥺", ["pleading", "puppy", "eyes"], []),
    ("😢", ["cry", "sad", "tear"], [":'(", "T_T"]),
    ("😭", ["crying", "sad"], []),
    ("😤", ["triumph", "frustrated"], []),
    ("😠", ["angry", "mad"], [">:(", ">:-("]),
    ("😡", ["rage", "angry"], []),
    ("🤬", ["cursing", "swear", "angry"], []),
    ("🤯", ["mind", "blown", "explode"], []),
    ("😳", ["flushed", "surprised"], []),
    ("🥵", ["hot", "sweat"], []),
    ("🥶", ["cold", "freeze"], []),
    ("😱", ["scream", "scared"], []),
    ("😨", ["fearful", "scared"], []),
    ("😰", ["anxious", "nervous"], []),
    ("😥", ["sad", "relieved"], []),
    ("😓", ["sweat", "nervous"], []),
    ("🤗", ["hug", "embrace"], []),
    ("🤔", ["thinking", "hmm"], []),
    ("🤭", ["giggle", "oops"], []),
    ("🤫", ["shh", "quiet", "silence"], []),
    ("🤥", ["liar", "pinocchio"], []),
    ("😶", ["blank", "no", "mouth"], []),
    ("😐", ["neutral", "meh"], [":|", ":-|"]),
    ("😑", ["expressionless", "unamused"], []),
    ("😬", ["grimace", "awkward"], []),
    ("🙄", ["roll", "eyes"], []),
    ("😯", ["surprised", "shocked"], [":o", ":-o", ":O", ":-O"]),
    ("😦", ["frown", "surprised"], []),
    ("😧", ["anguished", "shocked"], []),
    ("😮", ["open", "mouth", "surprised"], []),
    ("😲", ["astonished", "shocked"], []),
    ("🥱", ["yawn", "tired", "bored"], []),
    ("😴", ["sleep", "zzz"], []),
    ("🤤", ["drool", "sleep"], []),
    ("😪", ["sleepy", "tired"], []),
    ("😵", ["dizzy", "confused"], ["x_x", "X_X"]),
    ("🤐", ["zipper", "mouth", "shut"], []),
    ("🥴", ["woozy", "drunk"], []),

    # Hands
    ("👍", ["thumbs", "up", "yes", "good"], ["+1"]),
    ("👎", ["thumbs", "down", "no", "bad"], ["-1"]),
    ("👌", ["ok", "okay", "good"], []),
    ("✌️", ["peace", "victory"], []),
    ("🤞", ["fingers", "crossed", "luck"], []),
    ("🤟", ["love", "you"], []),
    ("🤘", ["rock", "metal"], []),
    ("🤙", ["call", "hang", "loose"], []),
    ("👈", ["point", "left"], []),
    ("👉", ["point", "right"], []),
    ("👆", ["point", "up"], []),
    ("👇", ["point", "down"], []),
    ("☝️", ["point", "up"], []),
    ("✋", ["hand", "stop"], []),
    ("🤚", ["raised", "back", "hand"], []),
    ("🖐️", ["hand", "fingers"], []),
    ("🖖", ["vulcan", "spock"], []),
    ("👋", ["wave", "hello", "bye"], []),
    ("🤝", ["handshake", "deal"], []),
    ("💪", ["muscle", "strong", "flex"], []),
    ("🦾", ["robot", "arm"], []),
    ("🖕", ["middle", "finger"], []),
    ("✍️", ["write", "pen"], []),
    ("🙏", ["pray", "thanks", "please"], []),
    ("👏", ["clap", "applause"], []),
    ("🤲", ["palms", "together"], []),
    ("🙌", ["celebrate", "hands", "up"], []),
    ("👐", ["open", "hands"], []),
    ("🤜", ["right", "fist"], []),
    ("🤛", ["left", "fist"], []),
    ("✊", ["fist", "power"], []),
    ("👊", ["punch", "fist", "bump"], []),

    # Hearts & Symbols
    ("❤️", ["heart", "love", "red"], ["<3"]),
    ("🧡", ["orange", "heart", "love"], []),
    ("💛", ["yellow", "heart", "love"], []),
    ("💚", ["green", "heart", "love"], []),
    ("💙", ["blue", "heart", "love"], []),
    ("💜", ["purple", "heart", "love"], []),
    ("🖤", ["black", "heart"], []),
    ("🤍", ["white", "heart"], []),
    ("🤎", ["brown", "heart"], []),
    ("💔", ["broken", "heart", "sad"], ["</3"]),
    ("❤️‍🔥", ["fire", "heart", "love"], []),
    ("❤️‍🩹", ["healing", "heart"], []),
    ("💕", ["two", "hearts", "love"], []),
    ("💞", ["revolving", "hearts"], []),
    ("💓", ["beating", "heart"], []),
    ("💗", ["growing", "heart"], []),
    ("💖", ["sparkling", "heart"], []),
    ("💘", ["cupid", "arrow", "love"], []),
    ("💝", ["heart", "ribbon", "gift"], []),
    ("💟", ["heart", "decoration"], []),
    ("🔥", ["fire", "hot", "lit"], []),
    ("⭐", ["star", "excellent"], []),
    ("✨", ["sparkle", "shine"], []),
    ("💫", ["dizzy", "star"], []),
    ("💥", ["boom", "explosion"], []),
    ("💢", ["anger", "symbol"], []),
    ("💦", ["sweat", "droplets"], []),
    ("💨", ["dash", "fast", "wind"], []),
    ("🎉", ["party", "celebrate"], []),
    ("🎊", ["confetti", "celebrate"], []),
    ("🎈", ["balloon", "party"], []),
    ("🎀", ["ribbon", "bow"], []),
    ("🎁", ["gift", "present"], []),
    ("🏆", ["trophy", "win", "award"], []),
    ("🥇", ["gold", "medal", "first"], []),
    ("🥈", ["silver", "medal", "second"], []),
    ("🥉", ["bronze", "medal", "third"], []),
]


def show_emoji_picker_dialog(parent) -> Optional[str]:
    """
    Show emoji picker dialog.

    Args:
        parent: Parent widget

    Returns:
        Selected emoji string, or None if cancelled
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Choose Emoji")
    dialog.setMinimumWidth(480)
    dialog.setMinimumHeight(400)
    dialog.setMaximumHeight(600)

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("<b>Choose an emoji:</b>"))

    # Search field
    search_field = QLineEdit()
    search_field.setPlaceholderText("Search emojis... (try ':D', 'smile', 'sad', ':rofl:')")
    layout.addWidget(search_field)

    # Create scrollable area for emoji groups
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    scroll_widget = QWidget()
    scroll_layout = QVBoxLayout(scroll_widget)
    scroll_layout.setSpacing(15)

    # Track selected emoji
    selected_emoji = [None]  # Use list to allow modification in nested function
    emoji_buttons = []  # Keep track of all buttons for search filtering

    def on_emoji_clicked(emoji):
        """Handle emoji selection."""
        selected_emoji[0] = emoji
        dialog.accept()

    # Build emoji groups from EMOJI_DATA
    emoji_groups = {
        "Faces": [],
        "Hands": [],
        "Hearts": [],
    }

    for emoji, keywords, text_reps in EMOJI_DATA:
        # Categorize by keywords
        if any(kw in keywords for kw in ["thumbs", "hand", "hands", "fist", "point", "wave", "clap", "pray", "muscle",
                                          "fingers", "finger", "palm", "palms", "peace", "vulcan", "punch", "ok",
                                          "handshake", "rock", "metal", "call", "arm", "write", "pen", "celebrate", "you"]):
            emoji_groups["Hands"].append((emoji, keywords, text_reps))
        elif any(kw in keywords for kw in ["fire", "star", "party", "trophy", "medal", "balloon", "gift", "ribbon", "confetti"]):
            emoji_groups["Hearts"].append((emoji, keywords, text_reps))
        elif emoji in ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❤️‍🔥", "❤️‍🩹", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟"]:
            emoji_groups["Hearts"].append((emoji, keywords, text_reps))
        else:
            emoji_groups["Faces"].append((emoji, keywords, text_reps))

    # Group labels for navigation
    group_labels = {}

    # Create emoji groups with labels
    for group_name, emojis in emoji_groups.items():
        if not emojis:
            continue

        # Group label
        label = QLabel(f"<b>{group_name}</b>")
        scroll_layout.addWidget(label)
        group_labels[group_name] = label

        # Grid for this group
        group_grid = QGridLayout()
        group_grid.setSpacing(5)
        group_grid.setContentsMargins(0, 0, 0, 0)

        # Add emoji buttons in 8 columns
        for i, (emoji, keywords, text_reps) in enumerate(emojis):
            row = i // 8
            col = i % 8
            btn = QPushButton(emoji)
            btn.setFixedSize(50, 50)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 24px;
                    font-family: "Noto Color Emoji", "Apple Color Emoji", "Segoe UI Emoji", monospace;
                    padding: 2px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)
            btn.clicked.connect(lambda checked=False, e=emoji: on_emoji_clicked(e))

            # Store metadata for search
            btn.setProperty("emoji_keywords", keywords)
            btn.setProperty("emoji_text_reps", text_reps)
            btn.setProperty("emoji_char", emoji)
            emoji_buttons.append(btn)

            group_grid.addWidget(btn, row, col)

        scroll_layout.addLayout(group_grid)

    # Finalize scroll area
    scroll_area.setWidget(scroll_widget)
    layout.addWidget(scroll_area)

    # Category navigation buttons
    nav_layout = QHBoxLayout()
    nav_layout.setSpacing(5)

    for group_name in emoji_groups.keys():
        if group_name not in group_labels:
            continue
        nav_btn = QPushButton(group_name)
        nav_btn.setFixedHeight(30)

        def make_scroll_callback(label):
            def scroll_to_label():
                # Get the label's Y position in the scroll widget
                y_pos = label.y()
                # Scroll so the label appears near the top with some padding
                scroll_area.verticalScrollBar().setValue(max(0, y_pos - 10))
            return scroll_to_label

        nav_btn.clicked.connect(make_scroll_callback(group_labels[group_name]))
        nav_layout.addWidget(nav_btn)

    nav_layout.addStretch()
    layout.addLayout(nav_layout)

    # Search functionality
    def on_search_changed(text):
        query = text.lower().strip()

        if not query:
            # Show all emojis
            for btn in emoji_buttons:
                btn.show()
        else:
            # Filter emojis
            for btn in emoji_buttons:
                keywords = btn.property("emoji_keywords")
                text_reps = btn.property("emoji_text_reps")

                # Check if query matches keywords or text representations
                matches = any(query in kw for kw in keywords) or any(query in tr.lower() for tr in text_reps)
                btn.setVisible(matches)

    search_field.textChanged.connect(on_search_changed)

    # Cancel button
    button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    # Focus search field for quick typing
    search_field.setFocus()

    # Show dialog and return result
    result = dialog.exec_()

    if result == QDialog.Accepted:
        return selected_emoji[0]
    else:
        return None
