"""
Spell Check Manager - Spell checking settings and management.

Handles:
- Loading spell check settings per conversation
- Toggling spell check on/off
- Setting spell check language
- Managing spell highlighter attachment to input field
"""

import logging
from PySide6.QtWidgets import QMenu
from PySide6.QtGui import QTextCursor, QAction
from collections import defaultdict


logger = logging.getLogger('siproxylin.chat_view.spell_check')


class SpellCheckManager:
    """
    Manages spell checking for the input field.

    Args:
        db: Database connection (get_db())
        input_field: MessageInputField widget
        spell_highlighter: EnchantHighlighter instance
    """

    def __init__(self, db, input_field, spell_highlighter):
        """Initialize spell check manager."""
        self.db = db
        self.input_field = input_field
        self.spell_highlighter = spell_highlighter
        self.current_conversation_id = None
        self.header_widget = None  # Will be set by ChatViewWidget

    def set_conversation(self, conversation_id):
        """Set current conversation and load its spell check settings."""
        self.current_conversation_id = conversation_id
        self.load_settings()

    def load_settings(self):
        """Load and apply spell check settings for current conversation."""
        if not self.current_conversation_id or not self.spell_highlighter:
            return

        # Get spell check enabled setting (default: enabled)
        enabled_str = self.db.get_conversation_setting(
            self.current_conversation_id,
            'spell_check_enabled',
            default='1'
        )
        enabled = enabled_str == '1'

        # Get language setting (default: en_US)
        language = self.db.get_conversation_setting(
            self.current_conversation_id,
            'spell_check_language',
            default='en_US'
        )

        logger.debug(f"Loading spell check settings: enabled={enabled}, language={language}")

        # Apply settings
        if enabled and self.spell_highlighter.is_available():
            self.spell_highlighter.set_language(language)
            self.spell_highlighter.setDocument(self.input_field.document())
        else:
            # Disable by detaching from document
            self.spell_highlighter.setDocument(None)

    def toggle_spell_check(self):
        """Toggle spell check enabled/disabled for current conversation."""
        if not self.current_conversation_id:
            return

        # Get current state
        enabled_str = self.db.get_conversation_setting(
            self.current_conversation_id,
            'spell_check_enabled',
            default='1'
        )
        current_enabled = enabled_str == '1'

        # Toggle
        new_enabled = not current_enabled
        self.db.set_conversation_setting(
            self.current_conversation_id,
            'spell_check_enabled',
            '1' if new_enabled else '0'
        )

        logger.debug(f"Spell check {'enabled' if new_enabled else 'disabled'} for conversation {self.current_conversation_id}")

        # Reload settings
        self.load_settings()

        # Update header button if available
        if self.header_widget:
            self.header_widget.update_spell_check_button()

    def set_language(self, language: str):
        """Set spell check language for current conversation."""
        if not self.current_conversation_id:
            return

        self.db.set_conversation_setting(
            self.current_conversation_id,
            'spell_check_language',
            language
        )

        logger.debug(f"Spell check language set to {language} for conversation {self.current_conversation_id}")

        # Reload settings
        self.load_settings()

        # Update header button if available
        if self.header_widget:
            self.header_widget.update_spell_check_button()

    def get_current_settings(self):
        """
        Get current spell check settings.

        Returns:
            tuple: (enabled: bool, language: str)
        """
        if not self.current_conversation_id:
            return (True, 'en_US')  # Defaults

        enabled_str = self.db.get_conversation_setting(
            self.current_conversation_id,
            'spell_check_enabled',
            default='1'
        )
        enabled = enabled_str == '1'

        language = self.db.get_conversation_setting(
            self.current_conversation_id,
            'spell_check_language',
            default='en_US'
        )

        return (enabled, language)

    def get_language_code(self):
        """
        Get short language code for button display (e.g., 'EN', 'RU', 'ES').

        Returns:
            str: Short language code in uppercase
        """
        _, language = self.get_current_settings()
        # Extract base language code (e.g., 'en' from 'en_US')
        base_lang = language.split('_')[0] if language else 'en'
        return base_lang.upper()

    def get_flag_emoji(self):
        """
        Get flag emoji for current language.

        Returns:
            str: Flag emoji corresponding to the language/locale
        """
        _, language = self.get_current_settings()

        # Map language codes to flag emojis
        # Format: language code (full or base) -> flag emoji
        flag_map = {
            # English variants
            'en_US': '🇺🇸',  # United States
            'en_GB': '🇬🇧',  # United Kingdom
            'en_CA': '🇨🇦',  # Canada
            'en_AU': '🇦🇺',  # Australia
            'en_NZ': '🇳🇿',  # New Zealand
            'en_IE': '🇮🇪',  # Ireland
            'en_ZA': '🇿🇦',  # South Africa
            'en_IN': '🇮🇳',  # India
            'en': '🇬🇧',     # Default English -> UK flag

            # Other languages (by country)
            'ru_RU': '🇷🇺',  # Russian
            'ru': '🇷🇺',
            'es_ES': '🇪🇸',  # Spanish (Spain)
            'es_MX': '🇲🇽',  # Spanish (Mexico)
            'es_AR': '🇦🇷',  # Spanish (Argentina)
            'es': '🇪🇸',     # Default Spanish
            'fr_FR': '🇫🇷',  # French
            'fr_CA': '🇨🇦',  # French (Canada)
            'fr': '🇫🇷',
            'de_DE': '🇩🇪',  # German
            'de_AT': '🇦🇹',  # German (Austria)
            'de_CH': '🇨🇭',  # German (Switzerland)
            'de': '🇩🇪',
            'it_IT': '🇮🇹',  # Italian
            'it': '🇮🇹',
            'pt_PT': '🇵🇹',  # Portuguese (Portugal)
            'pt_BR': '🇧🇷',  # Portuguese (Brazil)
            'pt': '🇵🇹',
            'pl_PL': '🇵🇱',  # Polish
            'pl': '🇵🇱',
            'nl_NL': '🇳🇱',  # Dutch
            'nl_BE': '🇧🇪',  # Dutch (Belgium)
            'nl': '🇳🇱',
            'sv_SE': '🇸🇪',  # Swedish
            'sv': '🇸🇪',
            'da_DK': '🇩🇰',  # Danish
            'da': '🇩🇰',
            'no_NO': '🇳🇴',  # Norwegian
            'no': '🇳🇴',
            'fi_FI': '🇫🇮',  # Finnish
            'fi': '🇫🇮',
            'cs_CZ': '🇨🇿',  # Czech
            'cs': '🇨🇿',
            'sk_SK': '🇸🇰',  # Slovak
            'sk': '🇸🇰',
            'hu_HU': '🇭🇺',  # Hungarian
            'hu': '🇭🇺',
            'ro_RO': '🇷🇴',  # Romanian
            'ro': '🇷🇴',
            'bg_BG': '🇧🇬',  # Bulgarian
            'bg': '🇧🇬',
            'el_GR': '🇬🇷',  # Greek
            'el': '🇬🇷',
            'tr_TR': '🇹🇷',  # Turkish
            'tr': '🇹🇷',
            'ar_SA': '🇸🇦',  # Arabic (Saudi Arabia)
            'ar_EG': '🇪🇬',  # Arabic (Egypt)
            'ar': '🇸🇦',
            'he_IL': '🇮🇱',  # Hebrew
            'he': '🇮🇱',
            'ja_JP': '🇯🇵',  # Japanese
            'ja': '🇯🇵',
            'zh_CN': '🇨🇳',  # Chinese (Simplified)
            'zh_TW': '🇹🇼',  # Chinese (Traditional)
            'zh': '🇨🇳',
            'ko_KR': '🇰🇷',  # Korean
            'ko': '🇰🇷',
            'vi_VN': '🇻🇳',  # Vietnamese
            'vi': '🇻🇳',
            'th_TH': '🇹🇭',  # Thai
            'th': '🇹🇭',
            'uk_UA': '🇺🇦',  # Ukrainian
            'uk': '🇺🇦',
            'lt_LT': '🇱🇹',  # Lithuanian
            'lt': '🇱🇹',
            'lv_LV': '🇱🇻',  # Latvian
            'lv': '🇱🇻',
            'et_EE': '🇪🇪',  # Estonian
            'et': '🇪🇪',
        }

        # Try full locale first (e.g., 'en_US'), then base language (e.g., 'en')
        if language in flag_map:
            return flag_map[language]

        # Try base language code
        base_lang = language.split('_')[0] if '_' in language else language
        if base_lang in flag_map:
            return flag_map[base_lang]

        # Default fallback: show language code as text
        return base_lang.upper()

    def create_spell_check_menu(self, parent_menu):
        """
        Create spell check menu for popup menu (called by button).

        Args:
            parent_menu: QMenu to populate with spell check options

        Returns:
            QMenu: The menu (same as parent_menu)
        """
        if not self.current_conversation_id:
            logger.warning("Cannot create spell check menu: no conversation selected")
            return parent_menu

        from PySide6.QtWidgets import QMenu

        # Get current settings
        current_enabled, current_language = self.get_current_settings()

        # Enable/Disable toggle
        toggle_action = parent_menu.addAction("✓ Enabled" if current_enabled else "☐ Enabled")
        toggle_action.triggered.connect(self.toggle_spell_check)

        parent_menu.addSeparator()

        # Language selection
        if self.spell_highlighter and self.spell_highlighter.is_available():
            available_languages = self.spell_highlighter.get_available_languages()

            if available_languages:
                # Add all languages as flat list
                for lang in sorted(available_languages):
                    is_current = (lang == current_language)
                    action = parent_menu.addAction(f"{'✓' if is_current else '  '} {lang}")
                    action.triggered.connect(lambda checked, l=lang: self.set_language(l))
            else:
                no_dicts = parent_menu.addAction("(no dictionaries installed)")
                no_dicts.setEnabled(False)
        else:
            not_available = parent_menu.addAction("(spell check not available)")
            not_available.setEnabled(False)

        return parent_menu

    def replace_word(self, cursor, replacement):
        """
        Replace misspelled word with suggestion.

        Args:
            cursor: QTextCursor positioned at the word
            replacement: Replacement text
        """
        # Begin edit block to make it undoable as single operation
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText(replacement)
        cursor.endEditBlock()

    def add_word_to_dictionary(self, word):
        """
        Add word to personal dictionary.

        Args:
            word: Word to add
        """
        if self.spell_highlighter:
            self.spell_highlighter.add_to_dictionary(word)
