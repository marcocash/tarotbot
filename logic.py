import hashlib
import random
from tarot_data import FULL_DECK

# Темы для подкрутки вероятности (оставляем)
THEMES = {
    "love": {
        "keywords": ["любовь", "отношения", "чувства", "муж", "жена", "брак", "парень", "секс"],
        "boost_suits": ["cups"],
        "boost_ids": ["maj_6", "maj_3", "maj_15", "c2", "c10"]
    },
    "career": {
        "keywords": ["работа", "деньги", "бизнес", "карьера", "проект", "зарплата", "финансы"],
        "boost_suits": ["pentacles", "wands"],
        "boost_ids": ["maj_1", "maj_4", "maj_10", "p1", "p10"]
    }
}


def get_deck_subset(deck_type):
    """Фильтрует колоду: только старшие или вся"""
    if deck_type == 'major':
        return [card for card in FULL_DECK if card['suit'] == 'major']
    return list(FULL_DECK)


def _prepare_weighted_deck(question, deck_type='full', exclude_ids=None):
    deck = get_deck_subset(deck_type)
    excluded = set(exclude_ids or [])
    if excluded:
        deck = [card for card in deck if card.get("id") not in excluded]

    weights = []
    question_lower = (question or "").lower()

    active_boosts = {"suits": [], "ids": []}
    for _, data in THEMES.items():
        if any(word in question_lower for word in data["keywords"]):
            active_boosts["suits"].extend(data["boost_suits"])
            active_boosts["ids"].extend(data["boost_ids"])

    for card in deck:
        weight = 1.0
        if card["suit"] in active_boosts["suits"]:
            weight += 3.0
        if card["id"] in active_boosts["ids"]:
            weight += 5.0
        weights.append(weight)

    return deck, weights


def _stable_seed(*parts: object) -> int:
    payload = "||".join(str(part or "") for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _draw_unique_cards(deck, weights, num_cards, rng=None):
    rng = rng or random
    num_cards = min(num_cards, len(deck))
    chosen_cards = []

    for _ in range(num_cards):
        card_template = rng.choices(deck, weights=weights, k=1)[0]
        idx = deck.index(card_template)
        deck.pop(idx)
        weights.pop(idx)

        final_card = card_template.copy()
        final_card['is_reversed'] = rng.random() < 0.15
        chosen_cards.append(final_card)

    return chosen_cards


def draw_reading(question, deck_type='full', num_cards=3, seed_hint=None):
    deck, weights = _prepare_weighted_deck(question, deck_type)
    rng = None
    if seed_hint is not None:
        seed = _stable_seed("reading", seed_hint, (question or "").lower().strip(), deck_type, num_cards)
        rng = random.Random(seed)
    return _draw_unique_cards(deck, weights, num_cards, rng=rng)


def draw_additional_cards(question, deck_type='full', num_cards=1, exclude_ids=None, seed_hint=None):
    deck, weights = _prepare_weighted_deck(question, deck_type, exclude_ids=exclude_ids)
    rng = None
    if seed_hint is not None:
        excluded = ",".join(sorted(str(item) for item in (exclude_ids or [])))
        seed = _stable_seed(
            "extend",
            seed_hint,
            (question or "").lower().strip(),
            deck_type,
            num_cards,
            excluded,
        )
        rng = random.Random(seed)
    return _draw_unique_cards(deck, weights, num_cards, rng=rng)
