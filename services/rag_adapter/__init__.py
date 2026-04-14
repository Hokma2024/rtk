"""Адаптер между старым контрактом RagResponse и реальным RAG.

Реальный RAG возвращает свободный markdown-текст в поле `answer`, что
сильно отличается от структурированного `required_actions`-плана мок-RAG.
Этот адаптер принимает стандартный RagRequest, вызывает реальный RAG,
классифицирует ответ по типу (direct/batch_historical/general_guidance/
documentation/empty) и отдаёт отфильтрованный текст в расширенном
RagResponse (answer_text, sources, parameters.rag_*).
"""
