"""
Временные тулзы для проверки агента
"""
from langchain_core.tools import tool

@tool
async def off_comp():
    """Выключает компьютер пользователя"""
    print("🔌 Выключаю компьютер...")
    return "Компьютер выключен"

@tool
async def restart_comp():
    """Перезагружает компьютер"""
    print("🔄 Перезагружаю компьютер...")
    return "Компьютер перезагружается"

@tool
async def update_software():
    """Обновляет программное обеспечение до последней версии"""
    print("📦 Обновляю программное обеспечение...")
    return "Программное обеспечение обновлено"

@tool
async def check_antivirus():
    """Запускает проверку антивирусом"""
    print("🛡️ Запускаю проверку антивирусом...")
    return "Проверка антивирусом запущена"

@tool
async def close_tabs():
    """Закрывает все открытые вкладки в браузере"""
    print("🗑️ Закрываю все вкладки...")
    return "Все вкладки закрыты"

@tool
async def reset_password():
    """Сбрасывает пароль пользователя"""
    print("🔐 Сбрасываю пароль...")
    return "Пароль сброшен"

@tool
async def call_admin():
    """Вызывает администратора для решения сложной проблемы"""
    print("👨‍💻 Вызываю администратора...")
    return "Администратор вызван"

# Список всех инструментов
tools = [off_comp, reset_password, restart_comp, update_software, check_antivirus, close_tabs, call_admin]