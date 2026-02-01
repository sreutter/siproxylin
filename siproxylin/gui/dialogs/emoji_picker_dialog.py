"""
Emoji picker dialog for message reactions.

Shows a grid of common emoji reactions for the user to select.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel,
    QDialogButtonBox, QPushButton, QLineEdit
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


def _store_sent_reaction(account_manager, account_id, message_id, emoji):
    """
    Store a sent reaction locally for immediate feedback.

    Args:
        account_manager: AccountManager instance
        account_id: Current account ID
        message_id: Message ID to react to
        emoji: Emoji string, or None to remove reactions
    """
    import time
    from slixmpp.jid import JID
    from ...db.database import get_db

    db = get_db()
    account = account_manager.get_account(account_id)
    if not account:
        return

    try:
        # Find content_item by message_id (search both messages and file transfers)
        content_item = db.fetchone("""
            SELECT ci.id, ci.conversation_id, c.type as conv_type, ci.time
            FROM content_item ci
            JOIN message m ON ci.foreign_id = m.id AND ci.content_type = 0
            JOIN conversation c ON ci.conversation_id = c.id
            WHERE m.account_id = ?
              AND (m.origin_id = ? OR m.stanza_id = ? OR m.message_id = ?)

            UNION

            SELECT ci.id, ci.conversation_id, c.type as conv_type, ci.time
            FROM content_item ci
            JOIN file_transfer ft ON ci.foreign_id = ft.id AND ci.content_type = 2
            JOIN conversation c ON ci.conversation_id = c.id
            WHERE ft.account_id = ?
              AND (ft.origin_id = ? OR ft.stanza_id = ? OR ft.message_id = ?)

            ORDER BY ci.time DESC
            LIMIT 1
        """, (account_id, message_id, message_id, message_id,
              account_id, message_id, message_id, message_id))

        if not content_item:
            logger.warning(f"Could not find message {message_id} to store reaction")
            return

        content_item_id = content_item['id']
        conv_type = content_item['conv_type']  # 0=chat, 1=groupchat
        reaction_time = int(time.time() * 1000)

        # Handle MUC vs 1-1 reactions - use occupant_id for MUC, jid_id for 1-1
        if conv_type == 1:  # MUC
            # Get conversation JID to lookup room
            conv_jid_row = db.fetchone("""
                SELECT c.jid_id, j.bare_jid
                FROM conversation c
                JOIN jid j ON c.jid_id = j.id
                WHERE c.id = ?
            """, (content_item['conversation_id'],))

            if not conv_jid_row:
                logger.error(f"Failed to get conversation JID")
                return

            room_jid_id = conv_jid_row['jid_id']
            room_jid = conv_jid_row['bare_jid']

            # Get our nickname in this room from client's rooms config
            if room_jid not in account.client.rooms:
                logger.error(f"Room {room_jid} not in client's rooms config")
                return

            our_nick = account.client.rooms[room_jid].get('nick')
            if not our_nick:
                logger.error(f"Failed to get our nickname in MUC {room_jid}")
                return

            # Get or create occupant entry
            db.execute("""
                INSERT INTO occupant (account_id, room_jid_id, nick)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id, room_jid_id, nick) DO NOTHING
            """, (account_id, room_jid_id, our_nick))

            occupant_row = db.fetchone("""
                SELECT id FROM occupant
                WHERE account_id = ? AND room_jid_id = ? AND nick = ?
            """, (account_id, room_jid_id, our_nick))

            if not occupant_row:
                logger.error(f"Failed to get occupant.id for {our_nick}")
                return

            occupant_id = occupant_row['id']

            if emoji:
                # Store MUC reaction using occupant_id
                db.execute("""
                    INSERT INTO reaction (account_id, content_item_id, occupant_id, time, emojis)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, content_item_id, occupant_id)
                    DO UPDATE SET emojis = excluded.emojis, time = excluded.time
                """, (account_id, content_item_id, occupant_id, reaction_time, emoji))
            else:
                # Remove MUC reaction
                db.execute("""
                    DELETE FROM reaction
                    WHERE account_id = ? AND content_item_id = ? AND occupant_id = ?
                """, (account_id, content_item_id, occupant_id))

        else:  # 1-1 chat
            # Get our own jid_id
            our_jid = account.client.boundjid.bare
            jid_row = db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (our_jid,))
            if not jid_row:
                # Create JID entry for ourselves
                db.execute("INSERT OR IGNORE INTO jid (bare_jid) VALUES (?)", (our_jid,))
                db.commit()
                jid_row = db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (our_jid,))
                if not jid_row:
                    logger.error(f"Failed to get jid_id for {our_jid}")
                    return

            jid_id = jid_row['id']

            if emoji:
                # Store 1-1 reaction using jid_id
                db.execute("""
                    INSERT INTO reaction (account_id, content_item_id, jid_id, time, emojis)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, content_item_id, jid_id)
                    DO UPDATE SET emojis = excluded.emojis, time = excluded.time
                """, (account_id, content_item_id, jid_id, reaction_time, emoji))
            else:
                # Remove 1-1 reaction
                db.execute("""
                    DELETE FROM reaction
                    WHERE account_id = ? AND content_item_id = ? AND jid_id = ?
                """, (account_id, content_item_id, jid_id))

        db.commit()
        logger.debug(f"Stored sent reaction locally: {emoji} on message {message_id}")

    except Exception as e:
        logger.error(f"Failed to store sent reaction: {e}")
        import traceback
        logger.error(traceback.format_exc())


def show_emoji_picker_dialog(parent, message_id, account_manager, account_id, current_jid, chat_view=None, mode="reaction", input_field=None):
    """
    Show emoji picker dialog for reacting to a message or inserting emoji into input.

    Args:
        parent: Parent widget
        message_id: The message ID to react to (origin_id or stanza_id) - only for mode="reaction"
        account_manager: AccountManager instance
        account_id: Current account ID
        current_jid: Current conversation JID
        chat_view: ChatView instance for refreshing after reaction
        mode: "reaction" to send reaction, "insert" to insert emoji into input field
        input_field: MessageInputField widget - required for mode="insert"

    Returns:
        True if a reaction was sent or emoji was inserted, False otherwise
    """
    if not account_id or not current_jid:
        logger.error("Cannot show emoji picker: no active conversation")
        return False

    account = account_manager.get_account(account_id)
    if not account or not account.is_connected():
        logger.error(f"Cannot show emoji picker: account not connected")
        return False

    dialog = QDialog(parent)
    if mode == "reaction":
        dialog.setWindowTitle("React to Message")
        label_text = "<b>Choose an emoji reaction:</b>"
    else:
        dialog.setWindowTitle("Insert Emoji")
        label_text = "<b>Choose an emoji:</b>"

    dialog.setMinimumWidth(480)
    dialog.setMinimumHeight(400)
    dialog.setMaximumHeight(600)  # Force scrolling so navigation buttons work

    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(label_text))

    # Search field
    search_field = QLineEdit()
    search_field.setPlaceholderText("Search emojis... (try ':D', 'smile', 'sad', ':rofl:')")
    layout.addWidget(search_field)

    # Category navigation buttons
    from PySide6.QtWidgets import QScrollArea, QWidget, QHBoxLayout
    nav_layout = QHBoxLayout()
    nav_layout.setSpacing(5)
    category_buttons = {}  # Will store buttons for each category

    # Create scrollable area for emoji groups
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    scroll_widget = QWidget()
    scroll_layout = QVBoxLayout(scroll_widget)
    scroll_layout.setSpacing(15)

    # Track if reaction was sent or emoji inserted
    action_completed = [False]  # Use list to allow modification in nested function
    emoji_buttons = []  # Keep track of all buttons for search filtering

    def send_reaction(emoji):
        """Send reaction and close dialog."""
        try:
            # Send reaction via XMPP
            account.client.send_reaction(current_jid, message_id, emoji)
            logger.info(f"Sent reaction {emoji} to message {message_id}")

            # Store locally for immediate feedback (optimistic UI)
            # This provides instant visual feedback that the reaction was sent
            _store_sent_reaction(account_manager, account_id, message_id, emoji)

            # Refresh the chat view to show the reaction immediately
            if chat_view:
                chat_view.refresh(send_markers=False)

            action_completed[0] = True
            dialog.accept()
        except Exception as e:
            logger.error(f"Failed to send reaction: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def insert_emoji(emoji):
        """Insert emoji at cursor position in input field and close dialog."""
        try:
            if not input_field:
                logger.error("No input field provided for emoji insertion")
                return

            # Get current cursor
            cursor = input_field.textCursor()

            # Insert emoji at cursor position
            cursor.insertText(emoji)

            # Set focus back to input field
            input_field.setFocus()

            action_completed[0] = True
            dialog.accept()
        except Exception as e:
            logger.error(f"Failed to insert emoji: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def remove_reaction():
        """Remove all reactions and close dialog."""
        try:
            # Remove reaction via XMPP
            account.client.remove_reaction(current_jid, message_id)
            logger.info(f"Removed all reactions from message {message_id}")

            # Remove locally for immediate feedback
            _store_sent_reaction(account_manager, account_id, message_id, None)

            # Refresh the chat view to show the change immediately
            if chat_view:
                chat_view.refresh(send_markers=False)

            action_completed[0] = True
            dialog.accept()
        except Exception as e:
            logger.error(f"Failed to remove reaction: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # Choose the callback based on mode
    emoji_callback = send_reaction if mode == "reaction" else insert_emoji

    # Build emoji groups from EMOJI_DATA
    emoji_groups = {
        "Faces": [],
        "Hands": [],
        "Hearts": [],
    }

    for emoji, keywords, text_reps in EMOJI_DATA:
        # Categorize by first checking more specific categories
        # Check Hands first (to catch all hand gestures before they fall through to Faces)
        if any(kw in keywords for kw in ["thumbs", "hand", "hands", "fist", "point", "wave", "clap", "pray", "muscle",
                                          "fingers", "finger", "palm", "palms", "peace", "vulcan", "punch", "ok",
                                          "handshake", "rock", "metal", "call", "arm", "write", "pen", "celebrate", "you"]):
            emoji_groups["Hands"].append((emoji, keywords, text_reps))
        # Check Hearts (fire, stars, party symbols)
        elif any(kw in keywords for kw in ["fire", "star", "party", "trophy", "medal", "balloon", "gift", "ribbon", "confetti"]):
            emoji_groups["Hearts"].append((emoji, keywords, text_reps))
        # Check if it's primarily a heart emoji (explicit list)
        elif emoji in ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❤️‍🔥", "❤️‍🩹", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟"]:
            emoji_groups["Hearts"].append((emoji, keywords, text_reps))
        # Everything else goes to Faces
        else:
            emoji_groups["Faces"].append((emoji, keywords, text_reps))

    # Group labels to store for navigation
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
            btn.clicked.connect(lambda checked=False, e=emoji: emoji_callback(e))

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

    # Create navigation buttons (after scroll_area is set up)
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
        category_buttons[group_name] = nav_btn

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

    # Remove reaction button (only for reaction mode)
    if mode == "reaction":
        remove_btn = QPushButton("Remove All Reactions")
        remove_btn.clicked.connect(remove_reaction)
        layout.addWidget(remove_btn)

    # Cancel button
    button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
    button_box.rejected.connect(dialog.reject)
    layout.addWidget(button_box)

    # Focus search field for quick typing
    search_field.setFocus()

    dialog.exec_()
    return action_completed[0]
