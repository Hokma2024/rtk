"""Фильтрация текста RAG-ответа под конкретный тип ответа.

Каждый тип ответа обрабатывается своей стратегией:

- ``direct``: вырезаем пункты, в которых упомянут current_order_id,
  добавляем 1 соседний пункт для контекста.
- ``batch_historical``: нормализуем чужие order_id (заменяем на
  ``<other_order>``), оставляем первые N пунктов с глаголами действий.
- ``general_guidance``: оставляем пункты с глаголами действий и
  ключевыми словами предметной области.
- ``documentation``: возвращаем пустую строку — агент работает по
  precheck + fallback-плану.
- ``empty``: пустая строка.

Все стратегии соблюдают общий лимит на длину (по умолчанию 1500
символов), чтобы не раздувать контекст LLM.
"""

from __future__ import annotations

import re

from .classifier import (
    ACTION_VERBS,
    DOMAIN_KEYWORDS,
    ORDER_ID_RE,
    extract_order_ids,
)

DEFAULT_MAX_LEN = 1500
DEFAULT_MAX_ITEMS = 5

# Нумерованный пункт в markdown: "1.", "12.", "1)" и т.п. в начале строки.
NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)


def _split_into_items(text: str) -> list[str]:
    """Разбивает markdown-текст на отдельные нумерованные пункты.

    Если в тексте нет нумерации, возвращает список из одного элемента —
    самого текста. Если есть — разбивает по номеру пункта, сохраняя
    исходную формулировку.
    """
    if not text:
        return []

    # Ищем позиции нумерованных пунктов.
    positions = [m.start() for m in NUMBERED_ITEM_RE.finditer(text)]
    if not positions:
        # Нет нумерации — пробуем разбить по пустым строкам.
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs or [text.strip()]

    # Есть нумерация — режем по позициям, захватывая всё до следующего номера.
    items: list[str] = []
    # Префикс до первого номера (заголовок "**Рекомендация:**" и т.п.) — пропускаем.
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        chunk = text[pos:end].strip()
        if chunk:
            items.append(chunk)
    return items


def _contains_action(item_lower: str) -> bool:
    return any(verb in item_lower for verb in ACTION_VERBS)


def _contains_domain(item_lower: str) -> bool:
    return any(kw in item_lower for kw in DOMAIN_KEYWORDS)


def _cap_length(text: str, max_len: int) -> str:
    """Обрезает текст до max_len символов, сохраняя целостность строк."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # Режем по последней целой строке, чтобы не получать огрызки.
    newline_idx = cut.rfind("\n")
    if newline_idx > max_len // 2:
        cut = cut[:newline_idx]
    return cut.rstrip() + "\n…"


def _filter_direct(text: str, current_order_id: str, max_items: int) -> str:
    """Извлекает пункты с current_order_id + 1 соседний для контекста."""
    items = _split_into_items(text)
    if not items:
        return text.strip()

    kept_indices: set[int] = set()
    for idx, item in enumerate(items):
        if current_order_id in item:
            kept_indices.add(idx)
            # Следующий пункт часто поясняет контекст.
            if idx + 1 < len(items):
                kept_indices.add(idx + 1)

    if not kept_indices:
        # Защита от случая, когда классификатор решил direct, но
        # конкретное упоминание order_id пропало при нормализации.
        return text.strip()

    ordered = [items[i] for i in sorted(kept_indices)][:max_items]
    return "\n".join(ordered)


def _filter_batch_historical(text: str, current_order_id: str, max_items: int) -> str:
    """Оставляет первые N пунктов с действиями, нормализует чужие order_id.

    Чужие order_id заменяются на плейсхолдер ``<other_order>``, чтобы LLM
    случайно не подставила их в параметры вызовов инструментов.
    """
    items = _split_into_items(text)
    if not items:
        items = [text.strip()] if text.strip() else []

    picked: list[str] = []
    for item in items:
        if len(picked) >= max_items:
            break
        item_lower = item.lower()
        if _contains_action(item_lower):
            picked.append(item)

    # Если по глаголам ничего не нашли — берём первые max_items как есть.
    if not picked:
        picked = items[:max_items]

    normalized: list[str] = []
    for item in picked:

        def _replace(match: re.Match[str]) -> str:
            found = match.group(0)
            return found if found == current_order_id else "<other_order>"

        normalized.append(ORDER_ID_RE.sub(_replace, item))

    return "\n".join(normalized)


def _filter_general_guidance(text: str, max_items: int) -> str:
    """Оставляет пункты с глаголами действий и доменными ключевыми словами."""
    items = _split_into_items(text)
    if not items:
        return text.strip()

    picked: list[str] = []
    for item in items:
        if len(picked) >= max_items:
            break
        item_lower = item.lower()
        if _contains_action(item_lower) and _contains_domain(item_lower):
            picked.append(item)

    if not picked:
        # Мягкий откат: берём по одному критерию или первые пункты.
        for item in items:
            if len(picked) >= max_items:
                break
            if _contains_action(item.lower()) or _contains_domain(item.lower()):
                picked.append(item)

    return "\n".join(picked or items[:max_items])


def filter_rag_response(
    kind: str,
    text: str,
    current_order_id: str,
    *,
    max_len: int = DEFAULT_MAX_LEN,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> str:
    """Возвращает отфильтрованный текст RAG для конкретного типа ответа.

    :param kind: тип из :func:`classifier.classify_rag_response`.
    :param text: исходный ``answer`` от реального RAG.
    :param current_order_id: order_id текущего тикета.
    :param max_len: предел длины выходного текста (символы).
    :param max_items: предел количества пунктов.
    """
    if kind in ("documentation", "empty"):
        return ""

    if not text:
        return ""

    if kind == "direct":
        out = _filter_direct(text, current_order_id, max_items)
    elif kind == "batch_historical":
        out = _filter_batch_historical(text, current_order_id, max_items)
    elif kind == "general_guidance":
        out = _filter_general_guidance(text, max_items)
    else:
        out = text.strip()

    return _cap_length(out, max_len)


def summarize_order_ids(text: str, current_order_id: str) -> tuple[list[str], bool]:
    """Возвращает (уникальные_order_id, найден_ли_текущий)."""
    ids = extract_order_ids(text)
    return ids, current_order_id in ids
