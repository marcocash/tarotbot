from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config

def period_label(days: int) -> str:
    labels = {
        1: "24 часа",
        7: "7 дней",
        30: "1 месяц",
        60: "2 месяца",
        90: "3 месяца",
        365: "1 год",
    }
    return labels.get(days, f"{days} дней")


def yoomoney_price(days: int) -> int:
    price = config.PRICES_RUB.get(days, 0)
    if not isinstance(price, (int, float)):
        return 0
    return max(1, int(price))


def stars_price(days: int) -> int:
    rub_price = yoomoney_price(days)
    rub_per_star = max(0.01, float(getattr(config, "RUB_PER_STAR", 1.6)))
    stars = int(round(float(rub_price) / rub_per_star))
    return max(1, stars)


def request_pack_price(units: int) -> int:
    value = config.REQUEST_PACKS_RUB.get(units, 0)
    if not isinstance(value, (int, float)):
        return 0
    return max(1, int(value))


def request_pack_usdt(units: int) -> float:
    value = config.REQUEST_PACKS_USDT.get(units, 0.0)
    if not isinstance(value, (int, float)):
        return 0.0
    return max(0.01, float(value))


def request_pack_stars(units: int) -> int:
    rub_price = request_pack_price(units)
    rub_per_star = max(0.01, float(getattr(config, "RUB_PER_STAR", 1.6)))
    stars = int(round(float(rub_price) / rub_per_star))
    return max(1, stars)

# --- ГЛАВНОЕ МЕНЮ (НИЖНЕЕ) ---
def get_main_menu(user_id: int | None = None):
    kb = [
        [
            types.KeyboardButton(text="🔮 Сделать расклад", style="primary"),
            types.KeyboardButton(text="😴 Разбор сна"),
        ],
        [
            types.KeyboardButton(text="🃏 Карта дня"),
            types.KeyboardButton(text="💞 Совместимость"),
        ],
        [
            types.KeyboardButton(text="👤 Мой профиль"),
        ],
    ]
    if user_id in config.ADMIN_IDS:
        kb.append([types.KeyboardButton(text="👑 Админ-панель")])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ПРОФИЛЬ ---
def get_profile_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="💎 Купить подписку",
                callback_data="open_sub_menu",
                style="primary",
            ),
            types.InlineKeyboardButton(
                text="💬 Купить расклады",
                callback_data="open_requests_menu",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔥 3 расклада за 14₽",
                callback_data="select_requests_3",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="⚙️ Настройки",
                callback_data="open_settings",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🫂 Рефералы (+1 день VIP)",
                callback_data="open_referral",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🎟 Промокод",
                callback_data="open_promo",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="✉️ Обратная связь",
                url="https://t.me/phizer_80",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="📝 Отзывы",
                url="https://t.me/otzivi_tarolog1",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="ℹ️ Информация",
                callback_data="info_help",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

def get_only_buy_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="💎 Купить подписку",
                callback_data="open_sub_menu",
                style="primary",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔙 Назад в профиль",
                callback_data="back_to_profile",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- МЕНЮ РЕФЕРАЛОВ ---
def get_referral_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="📊 Мои покупки по рефке",
                callback_data="open_referral_stats",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔙 Назад в профиль",
                callback_data="back_to_profile",
            )
        ]
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_referral_stats_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🫂 В меню рефералов",
                    callback_data="open_referral",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 Назад в профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )


def get_promo_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="promo_cancel",
                    style="danger",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )

# --- МЕНЮ ПОДПИСКИ ---
def get_subs_keyboard():
    ordered_days = [1, 7, 30, 60, 90, 365]
    kb: list[list[types.InlineKeyboardButton]] = []

    for days in ordered_days:
        price = config.PRICES_RUB.get(days)
        if price is None:
            continue
        prefix = "⚡" if days == 1 else "🗓"
        kb.append(
            [
                types.InlineKeyboardButton(
                    text=f"{prefix} {period_label(days)} - {int(price)}₽",
                    callback_data=f"select_days_{days}",
                )
            ]
        )

    kb.append(
        [
            types.InlineKeyboardButton(
                text="🔙 Назад в профиль",
                callback_data="back_to_profile",
            )
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_requests_keyboard() -> types.InlineKeyboardMarkup:
    ordered_units = [5, 10, 20, 50, 100]
    kb: list[list[types.InlineKeyboardButton]] = []

    for units in ordered_units:
        price = request_pack_price(units)
        if price <= 0:
            continue
        kb.append(
            [
                types.InlineKeyboardButton(
                    text=f"💬 {units} раскладов - {price}₽",
                    callback_data=f"select_requests_{units}",
                )
            ]
        )

    kb.append(
        [
            types.InlineKeyboardButton(
                text="🔙 Назад в профиль",
                callback_data="back_to_profile",
            )
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


# --- ВЫБОР СПОСОБА ОПЛАТЫ ---
def get_payment_method_keyboard(days: int, show_extended: bool = False):
    rub_price = yoomoney_price(days)
    stars_amount = stars_price(days)
    price_usdt = config.PRICES_USDT.get(days, 0)

    kb = [
        [
            types.InlineKeyboardButton(
                text=f"🟣 ЮMoney / Карта РФ ({rub_price}₽)",
                callback_data=f"pay_method_yoomoney_{days}",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=f"⭐ Telegram Stars ({stars_amount}⭐)",
                callback_data=f"pay_method_stars_{days}",
            )
        ],
    ]

    if show_extended:
        kb.extend(
            [
                [
                    types.InlineKeyboardButton(
                        text=f"🔵 CryptoBot ({price_usdt} USDT)",
                        callback_data=f"pay_method_crypto_{days}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🎁 NFT-Подарки (вручную)",
                        callback_data=f"pay_method_nft_{days}",
                    )
                ],
            ]
        )
    else:
        kb.append(
            [
                types.InlineKeyboardButton(
                    text="➕ Другие способы оплаты",
                    callback_data=f"open_pay_methods_ext_{days}",
                )
            ]
        )

    kb.append(
        [
            types.InlineKeyboardButton(
                text="🔙 Назад к тарифам",
                callback_data="open_sub_menu",
            ),
            types.InlineKeyboardButton(
                text="👤 В профиль",
                callback_data="back_to_profile",
            ),
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_request_payment_method_keyboard(
    units: int,
    show_extended: bool = False,
) -> types.InlineKeyboardMarkup:
    rub_price = request_pack_price(units)
    stars_amount = request_pack_stars(units)
    price_usdt = request_pack_usdt(units)

    kb = [
        [
            types.InlineKeyboardButton(
                text=f"🟣 ЮMoney / Карта РФ ({rub_price}₽)",
                callback_data=f"pay_request_method_yoomoney_{units}",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=f"⭐ Telegram Stars ({stars_amount}⭐)",
                callback_data=f"pay_request_method_stars_{units}",
            )
        ],
    ]

    if show_extended:
        kb.extend(
            [
                [
                    types.InlineKeyboardButton(
                        text=f"🔵 CryptoBot ({price_usdt:g} USDT)",
                        callback_data=f"pay_request_method_crypto_{units}",
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🎁 NFT-Подарки (вручную)",
                        callback_data=f"pay_request_method_nft_{units}",
                    )
                ],
            ]
        )
    else:
        kb.append(
            [
                types.InlineKeyboardButton(
                    text="➕ Другие способы оплаты",
                    callback_data=f"open_request_pay_methods_ext_{units}",
                )
            ]
        )

    kb.append(
        [
            types.InlineKeyboardButton(
                text="🔙 Назад к пакетам",
                callback_data="open_requests_menu",
            ),
            types.InlineKeyboardButton(
                text="👤 В профиль",
                callback_data="back_to_profile",
            ),
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_tripwire_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔥 3 расклада за 14₽",
                    callback_data="select_requests_3",
                    style="success",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="⚡ VIP на 24 часа",
                    callback_data="open_pay_methods_1",
                    style="primary",
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="💬 Пакеты раскладов",
                    callback_data="open_requests_menu",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="💎 Все тарифы",
                    callback_data="open_sub_menu",
                )
            ],
        ]
    )


def get_dream_cancel_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_dream",
                    style="danger",
                )
            ]
        ]
    )


def get_dream_result_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="😴 Новый разбор сна",
                    callback_data="new_dream_reading",
                    style="primary",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )


def get_dream_buy_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔥 3 расклада за 14₽",
                    callback_data="select_requests_3",
                    style="success",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="💬 Пакеты раскладов",
                    callback_data="open_requests_menu",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )


def get_reading_cancel_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="cancel_reading",
                    style="danger",
                )
            ]
        ]
    )


# --- ВЫБОР КОЛИЧЕСТВА КАРТ ---
def get_cards_count_keyboard():
    kb = [
        [types.InlineKeyboardButton(text="1 карта", callback_data="count_1")],
        [types.InlineKeyboardButton(text="3 карты", callback_data="count_3")],
        [types.InlineKeyboardButton(text="6 карт", callback_data="count_6")],
        [types.InlineKeyboardButton(text="18 карт", callback_data="count_18")],
        [
            types.InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="cancel_reading",
                style="danger",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- ЗНАКИ ЗОДИАКА ---
def get_zodiac_keyboard():
    zodiacs = ["♈️ Овен", "♉️ Телец", "♊️ Близнецы", "♋️ Рак",
               "♌️ Лев", "♍️ Дева", "♎️ Весы", "♏️ Скорпион",
               "♐️ Стрелец", "♑️ Козерог", "♒️ Водолей", "♓️ Рыбы"]
    builder = InlineKeyboardBuilder()
    for z in zodiacs:
        sign_name = z.split()[1]
        builder.button(text=z, callback_data=f"zod_{sign_name}")
    builder.adjust(3)
    return builder.as_markup()

# --- РЕЗУЛЬТАТ ГАДАНИЯ ---
def get_result_keyboard(
    is_vip: bool = False,
    can_extend: bool = False,
    share_inline: bool = False,
):
    kb = [
        [
            types.InlineKeyboardButton(
                text="🔮 Новый расклад",
                callback_data="new_reading",
                style="primary",
            )
        ]
    ]

    if can_extend:
        kb.append(
            [
                types.InlineKeyboardButton(
                    text="➕ Докинуть карты",
                    callback_data="open_extend_cards",
                    style="primary",
                )
            ]
        )

    if share_inline:
        kb.append(
            [
                types.InlineKeyboardButton(
                    text="📤 Поделиться раскладом",
                    switch_inline_query="share_reading",
                )
            ]
        )

    kb.append(
        [
            types.InlineKeyboardButton(
                text="👤 В профиль",
                callback_data="back_to_profile",
            )
        ]
    )
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_upgrade_cta_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🔥 3 расклада за 14₽",
                    callback_data="select_requests_3",
                    style="success",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="💎 Открыть VIP",
                    callback_data="open_sub_menu",
                    style="primary",
                ),
                types.InlineKeyboardButton(
                    text="💬 Купить расклады",
                    callback_data="open_requests_menu",
                    style="success",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )


def get_vip_30_upsell_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💎 VIP 30 дней за 300₽",
                    callback_data="open_pay_methods_30",
                    style="primary",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👤 В профиль",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )


def get_extend_cards_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="+1 карта", callback_data="extend_cards_1")],
            [types.InlineKeyboardButton(text="+2 карты", callback_data="extend_cards_2")],
            [types.InlineKeyboardButton(text="+3 карты", callback_data="extend_cards_3")],
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="extend_cards_cancel",
                    style="danger",
                )
            ],
        ]
    )


def get_extend_retry_keyboard(add_count: int) -> types.InlineKeyboardMarkup:
    safe_count = add_count if add_count in {1, 2, 3} else 1
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"🔁 Повторить докид (+{safe_count})",
                    callback_data=f"extend_cards_{safe_count}",
                    style="primary",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="extend_cards_cancel",
                    style="danger",
                )
            ],
        ]
    )

# --- ЛИМИТ ---
def get_limit_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="🔥 3 расклада за 14₽",
                callback_data="select_requests_3",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="💎 Открыть VIP",
                callback_data="open_sub_menu",
                style="primary",
            ),
            types.InlineKeyboardButton(
                text="💬 Купить расклады",
                callback_data="open_requests_menu",
                style="success",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="👤 В профиль",
                callback_data="back_to_profile",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- НАСТРОЙКИ ---
def get_settings_keyboard(user_data):
    deck = user_data.get("setting_deck", "full")
    persona = user_data.get("persona", "neutral")
    length = user_data.get("setting_length", "short")

    deck_full = "✅ Полная" if deck == "full" else "Полная"
    deck_major = "✅ Только старшие" if deck == "major" else "Только старшие"

    pers_sup = "✅ Подружка" if persona == "supportive" else "Подружка"
    pers_sassy = "✅ Стерва" if persona == "sassy" else "Стерва"
    pers_exp = "✅ Эксперт" if persona == "neutral" else "Эксперт"

    len_short = "✅ Кратко" if length == "short" else "Кратко"
    len_long = "✅ Подробно" if length == "long" else "Подробно"

    kb = [
        [
            types.InlineKeyboardButton(
                text="🃏 Колода",
                callback_data="ignore",
                style="primary",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=deck_full,
                callback_data="set_deck_full",
            ),
            types.InlineKeyboardButton(
                text=deck_major,
                callback_data="set_deck_major",
            ),
        ],

        [
            types.InlineKeyboardButton(
                text="🎭 Личность",
                callback_data="ignore",
                style="primary",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=pers_sup,
                callback_data="set_persona_supportive",
            ),
            types.InlineKeyboardButton(
                text=pers_sassy,
                callback_data="set_persona_sassy",
            ),
            types.InlineKeyboardButton(
                text=pers_exp,
                callback_data="set_persona_neutral",
            ),
        ],

        [
            types.InlineKeyboardButton(
                text="📝 Ответ",
                callback_data="ignore",
                style="primary",
            )
        ],
        [
            types.InlineKeyboardButton(
                text=len_short,
                callback_data="set_length_short",
            ),
            types.InlineKeyboardButton(
                text=len_long,
                callback_data="set_length_long",
            ),
        ],

        [
            types.InlineKeyboardButton(
                text="🔙 В профиль",
                callback_data="back_to_profile",
            ),
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- ИНФОРМАЦИЯ И ПРАВИЛА ---
def get_info_keyboard():
    kb = [
        # Твоя ссылка на Пользовательское соглашение
        [
            types.InlineKeyboardButton(
                text="📜 Пользовательское соглашение",
                url="https://telegra.ph/Polzovatelskoe-soglashenie-Publichnaya-oferta-02-19-2",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔙 Назад в профиль",
                callback_data="back_to_profile",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- ПРОВЕРКА ПОДПИСКИ ---
def get_sub_check_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="📢 Подписаться на канал",
                url=config.CHANNEL_URL,
                style="primary",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="✅ Я подписался",
                callback_data="check_subscription",
                style="success",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)

# --- АДМИН ПАНЕЛЬ ---
def get_admin_keyboard():
    kb = [
        [
            types.InlineKeyboardButton(
                text="📜 История раскладов",
                callback_data="admin_history",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="💎 VIP база",
                callback_data="admin_vip_users",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🔎 Пользователь по ID",
                callback_data="admin_lookup_user",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="✉️ Личное сообщение по ID",
                callback_data="admin_dm_by_id",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="➕ Выдать расклады по ID",
                callback_data="admin_grant_requests",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="💳 Покупки VIP/раскладов",
                callback_data="admin_purchases",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="📈 Воронка продаж",
                callback_data="admin_funnel",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🫂 Реф-связки",
                callback_data="admin_ref_links",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="💰 Покупки по рефке",
                callback_data="admin_ref_purchases",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="📣 Рассылка",
                callback_data="admin_broadcast_start",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="🎟 Промокоды",
                callback_data="admin_promos",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="❌ Закрыть",
                callback_data="close_admin",
                style="danger",
            )
        ],
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=kb)


def get_admin_ref_filter_keyboard(
    prefix: str,
    month_choices: list[tuple[str, str]],
    selected_month: str | None = None,
) -> types.InlineKeyboardMarkup:
    rows: list[list[types.InlineKeyboardButton]] = [
        [
            types.InlineKeyboardButton(
                text="✅ Все время" if selected_month is None else "Все время",
                callback_data=f"{prefix}_month_all",
            )
        ]
    ]

    current_row: list[types.InlineKeyboardButton] = []
    for month_key, month_label in month_choices[:12]:
        current_row.append(
            types.InlineKeyboardButton(
                text=f"✅ {month_label}" if month_key == selected_month else month_label,
                callback_data=f"{prefix}_month_{month_key}",
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    rows.append(
        [
            types.InlineKeyboardButton(
                text="🔙 В админ-панель",
                callback_data="back_to_admin_menu",
            )
        ]
    )

    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_promo_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="➕ Создать промокод",
                    callback_data="admin_promo_create",
                    style="primary",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👥 Кто активировал",
                    callback_data="admin_promo_activations",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data="admin_promos",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 В админ-панель",
                    callback_data="back_to_admin_menu",
                )
            ],
        ]
    )


def get_admin_broadcast_confirm_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Отправить всем",
                    callback_data="admin_broadcast_confirm",
                    style="success",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="admin_broadcast_cancel",
                    style="danger",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 В админ-панель",
                    callback_data="back_to_admin_menu",
                )
            ],
        ]
    )
