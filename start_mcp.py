import sys
import os
import asyncio

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🚀 Запуск MCP сервера...")
print(f"📁 Текущая директория: {os.getcwd()}")

# Импортируем и запускаем сервер
try:
    from server import mcp
    
    if __name__ == "__main__":
        print("🔥 Запуск mcp.run(transport='stdio')...")
        mcp.run(transport="stdio")
except Exception as e:
    print(f"❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()