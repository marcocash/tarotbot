from aiogram.fsm.state import State, StatesGroup


class TarotStates(StatesGroup):
    waiting_for_question = State()
    waiting_for_count = State()
    waiting_for_first_sign = State()
    waiting_for_second_sign = State()
    waiting_for_dream_text = State()


class AdminStates(StatesGroup):
    waiting_broadcast_message = State()
    waiting_broadcast_confirm = State()
    waiting_promo_create = State()
    waiting_user_lookup_id = State()
    waiting_direct_message = State()
    waiting_grant_requests = State()


class PromoStates(StatesGroup):
    waiting_promo_code = State()
