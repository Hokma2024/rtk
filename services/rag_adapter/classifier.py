"""Классификация типа ответа реального RAG.

Реальный RAG возвращает свободный markdown-текст. В зависимости от
запроса и релевантности результата этот текст может быть:

- **direct**: прямые рекомендации на конкретный order_id, который есть в
  тексте и совпадает с запрашиваемым. Пример: «Перевести заявку X в Отказ».
- **batch_historical**: пачка похожих исторических кейсов — много разных
  order_id, ни один не совпадает с текущим (или текущий теряется среди
  десятков других).
- **general_guidance**: общее описание процесса без упоминания конкретных
  order_id, но с глаголами действий и ключевыми словами предметной
  области (ЕИССД, СУЛЗ, МРФ, статус, отказ и т.п.).
- **documentation**: ответ про спецификации, протоколы, разделы, авторов —
  не имеющий отношения к текущему тикету. Пример: «Изменение параметров
  в п. 3.5.25», «согласно изменениям от ...».
- **empty**: пустой ответ, либо слишком короткий для интерпретации.

Классификатор — чисто эвристический, работает на регулярных выражениях
и счётчиках ключевых слов. Его задача — быстро и детерминированно
выбрать стратегию фильтрации.
"""

from __future__ import annotations

import re

# Числа вида 1800003879409 (типичные order_id), а также варианты других
# длин — реальные order_id могут иметь разный формат.
ORDER_ID_RE = re.compile(r"\b\d{10,15}\b")

# Маркер нумерованного раздела документации вида "п. 3.5.25" или "п.3.5.25".
DOC_SECTION_RE = re.compile(r"п\.\s*\d+\.\d+(?:\.\d+)*", re.IGNORECASE)

ACTION_VERBS: frozenset[str] = frozenset(
    {
        "перевести",
        "закрыть",
        "высвободить",
        "исправить",
        "отправить",
        "проверить",
        "удалить",
        "добавить",
        "перезапустить",
        "скорректировать",
        "пересоздать",
        "перенести",
        "вернуть",
        "синхронизировать",
        "обновить",
        "зафиксировать",
    }
)

DOMAIN_KEYWORDS: frozenset[str] = frozenset(
    {
        "еиссд",
        "сулз",
        "мрф",
        "статус",
        "отказ",
        "серийный",
        "заявка",
        "заказ",
        "оборудование",
        "склад",
        "доставк",
    }
)

DOC_MARKERS: frozenset[str] = frozenset(
    {
        "параметр",
        "раздел",
        "документация",
        "спецификация",
        "согласно изменениям",
        "автор:",
        "автор:",
        "страниц",
        "протокол",
    }
)

MIN_TEXT_LENGTH = 50


def _count_keywords(text_lower: str, keywords: frozenset[str]) -> int:
    return sum(1 for kw in keywords if kw in text_lower)


def extract_order_ids(text: str) -> list[str]:
    """Возвращает список уникальных order_id, упомянутых в тексте (в порядке появления)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in ORDER_ID_RE.findall(text or ""):
        if match not in seen:
            seen.add(match)
            out.append(match)
    return out


def classify_rag_response(text: str, current_order_id: str) -> str:
    """Определяет тип ответа RAG по содержимому.

    :param text: сырой ``answer`` от реального RAG.
    :param current_order_id: order_id текущего тикета — для оценки релевантности.
    :returns: один из ``direct``, ``batch_historical``, ``general_guidance``,
        ``documentation``, ``empty``.
    """
    if not text or len(text.strip()) < MIN_TEXT_LENGTH:
        return "empty"

    lower = text.lower()

    doc_marker_count = _count_keywords(lower, DOC_MARKERS)
    has_doc_sections = bool(DOC_SECTION_RE.search(text))
    action_count = _count_keywords(lower, ACTION_VERBS)

    # Документация доминирует: много маркеров разделов/параметров и мало
    # глаголов действий. Даже если где-то мелькнёт order_id — это скорее
    # пример в протоколе, чем инструкция по тикету.
    if has_doc_sections or doc_marker_count >= 3:
        if action_count < 3:
            return "documentation"

    order_ids = extract_order_ids(text)

    # Если нашли >=4 разных order_id — это точно пачка похожих кейсов.
    # Даже если текущий order_id среди них — большая часть текста про
    # чужие заявки, фильтр обработает это отдельно.
    if len(order_ids) >= 4:
        return "batch_historical"

    # 1–3 order_id, текущий среди них → прямое действие.
    if current_order_id in order_ids:
        return "direct"

    # 1–3 order_id, но текущего нет. Редкий случай — трактуем как
    # batch_historical, чтобы фильтр нормализовал чужие идентификаторы.
    if order_ids:
        return "batch_historical"

    # Ни одного order_id, но есть глаголы действий и ключевые слова
    # предметной области → общее описание процесса.
    domain_count = _count_keywords(lower, DOMAIN_KEYWORDS)
    if action_count >= 2 and domain_count >= 1:
        return "general_guidance"

    # Ничего не подошло — самая осторожная категория, чтобы не сломать
    # агента. general_guidance даст LLM возможность проигнорировать текст,
    # если он бесполезен.
    return "general_guidance"
