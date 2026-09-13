"""Хелпер для сборки inline-кнопок с премиум-иконками и цветами."""

from typing import Optional

from aiogram.types import InlineKeyboardButton

from emojis import ICON


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
            Неактивированным ботам и без Premium иконки просто не видны.
    """
    kwargs: dict = {"text": text}
    if cb is not None:
        kwargs["callback_data"] = cb
    if url is not None:
        kwargs["url"] = url
    if style is not None:
        kwargs["style"] = style
    if icon is not None:
        icon_id = ICON.get(icon)
        if icon_id:
            kwargs["icon_custom_emoji_id"] = icon_id
    return InlineKeyboardButton(**kwargs)
