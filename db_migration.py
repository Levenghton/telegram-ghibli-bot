"""
Скрипт для миграции данных из SQLite в PostgreSQL.
"""
import os
import sqlite3
import asyncio
import asyncpg
import psycopg2
import logging
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем параметры подключения к PostgreSQL из переменных окружения
# или используем значения по умолчанию
PG_HOST = os.getenv('PG_HOST', 'localhost')
PG_PORT = os.getenv('PG_PORT', '5432')
PG_DB = os.getenv('PG_DB', 'telegram_bot')
PG_USER = os.getenv('PG_USER', 'postgres')
PG_PASSWORD = os.getenv('PG_PASSWORD', 'postgres')
PG_CONNECTION_STRING = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

# Путь к SQLite базе данных
SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')

async def create_pg_tables():
    """Создать таблицы в PostgreSQL базе данных."""
    try:
        connection = await asyncpg.connect(PG_CONNECTION_STRING)
        
        # Создаем таблицу users, аналогичную той, что в SQLite, но с учетом типов PostgreSQL
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                balance INTEGER DEFAULT 0,
                total_generations INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_generation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Создаем индекс для более быстрого поиска по user_id
            CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id);
        ''')
        
        logger.info("Таблицы в PostgreSQL успешно созданы")
        await connection.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка при создании таблиц в PostgreSQL: {e}")
        return False

async def migrate_data():
    """Мигрировать данные из SQLite в PostgreSQL."""
    try:
        # Подключаемся к SQLite
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_cursor = sqlite_conn.cursor()
        
        # Получаем всех пользователей из SQLite
        sqlite_cursor.execute('SELECT user_id, username, first_name, last_name, balance, total_generations, created_at, last_generation FROM users')
        users_data = sqlite_cursor.fetchall()
        
        if not users_data:
            logger.warning("Нет данных для миграции в SQLite базе")
            sqlite_conn.close()
            return False
        
        # Подключаемся к PostgreSQL
        pg_conn = await asyncpg.connect(PG_CONNECTION_STRING)
        
        # Мигрируем данные каждого пользователя
        for user in users_data:
            user_id, username, first_name, last_name, balance, total_generations, created_at, last_generation = user
            
            # Формируем правильные даты или используем текущее время, если дата некорректная
            try:
                created_at_dt = datetime.fromisoformat(created_at) if created_at else datetime.now()
            except (ValueError, TypeError):
                created_at_dt = datetime.now()
                
            try:
                last_generation_dt = datetime.fromisoformat(last_generation) if last_generation else datetime.now()
            except (ValueError, TypeError):
                last_generation_dt = datetime.now()
            
            # Вставляем данные пользователя в PostgreSQL
            await pg_conn.execute('''
                INSERT INTO users (user_id, username, first_name, last_name, balance, total_generations, created_at, last_generation)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = $2,
                    first_name = $3,
                    last_name = $4,
                    balance = $5,
                    total_generations = $6,
                    created_at = $7,
                    last_generation = $8
            ''', user_id, username or "", first_name or "", last_name or "", balance, total_generations, created_at_dt, last_generation_dt)
            
            logger.info(f"Мигрирован пользователь с ID {user_id}")
        
        # Закрываем соединения
        await pg_conn.close()
        sqlite_conn.close()
        
        logger.info(f"Миграция данных успешно завершена. Перенесено {len(users_data)} пользователей.")
        return True
    except Exception as e:
        logger.error(f"Ошибка при миграции данных: {e}")
        return False

async def test_pg_connection():
    """Проверить подключение к PostgreSQL."""
    try:
        conn = await asyncpg.connect(PG_CONNECTION_STRING)
        await conn.execute('SELECT 1')
        await conn.close()
        logger.info("Подключение к PostgreSQL успешно установлено")
        return True
    except Exception as e:
        logger.error(f"Ошибка подключения к PostgreSQL: {e}")
        return False

async def main():
    """Основная функция для создания структуры базы данных."""
    logger.info("Инициализация структуры базы данных PostgreSQL")
    
    # Проверяем подключение к PostgreSQL
    if not await test_pg_connection():
        logger.error("Невозможно подключиться к PostgreSQL. Миграция прервана.")
        return
    
    # Создаем таблицы в PostgreSQL
    if not await create_pg_tables():
        logger.error("Не удалось создать таблицы в PostgreSQL. Миграция прервана.")
        return
    
    logger.info("Структура базы данных PostgreSQL успешно создана!")

if __name__ == "__main__":
    # Запускаем миграцию
    asyncio.run(main())
