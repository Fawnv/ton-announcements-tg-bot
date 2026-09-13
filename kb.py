"""Хелпер для сборки inline-кнопок с премиум-иконками и цветами."""

import unicodedata
from typing import Optional

from aiogram.types import InlineKeyboardButton

from emojis import ICON


_EMOJI_JOINERS = {"\ufe0f", "\ufe0e", "\u200d", "\u20e3"}


def _strip_leading_emoji(text: str) -> str:
    """Убирает ведущие обычные emoji, если у кнопки есть premium icon.

    Нужен именно для кнопок вида ``btn("🔗 Открыть", icon="link")``:
    Telegram сам рисует ``icon_custom_emoji_id`` слева от текста, поэтому
    обычный emoji в ``text`` иначе отображается вторым значком.

    Удаляются только emoji/символы в самом начале строки. Emoji внутри или
    в конце текста (например ``"Цена: 129 ⭐"``) сохраняются.
    """
    value = text.lstrip()

    while value:
        first = value[0]
        category = unicodedata.category(first)

        # Большинство обычных emoji, стрелок, чеков, звезд и пиктограмм — So/Sk.
        if not category.startswith("S"):
            break

        i = 1
        while i < len(value):
            ch = value[i]
            cat = unicodedata.category(ch)
            if ch in _EMOJI_JOINERS or cat.startswith("M"):
                i += 1
                continue
            # После ZWJ следующий символ является частью emoji-последовательности.
            if i > 0 and value[i - 1] == "\u200d":
                i += 1
                continue
            break

        value = value[i:].lstrip()

    return value


def btn(
    text: str,
    cb: Optional[str] = None,
    url: Optional[str] = None,
    style: Optional[str] = None,
    icon: Optional[str] = None,
) -> InlineKeyboardButton:
    """Inline-кнопка.

    cb    — callback_data;
    url   — ссылка вместо callback;
    style — цвет кнопки ('success' / 'danger' / 'primary');
    icon  — премиум-иконка: ключ из emojis.ICON ('star', 'reject', ...).

    Если premium-иконка реально найдена, ведущие обычные emoji из ``text``
    автоматически убираются, чтобы Telegram не показывал две иконки подряд.
    """
    icon_id = ICON.get(icon) if icon is not None else None
    button_text = _strip_leading_emoji(text) if icon_id else text

    kwargs: dict = {"text": button_text}
    if cb is not None:
        kwargs["callback_data"] = cb
    if url is not None:
        kwargs["url"] = url
    if style is not None:
        kwargs["style"] = style
    if icon_id:
        kwargs["icon_custom_emoji_id"] = icon_id

    return InlineKeyboardButton(**kwargs)

