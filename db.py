"""
Модуль для асинхронной работы с базой данных PostgreSQL.
"""
import os
import logging
import asyncio
import asyncpg
from datetime import datetime
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logger = logging.getLogger(__name__)

# Жестко прописываем публичный URL подключения к PostgreSQL в Railway
# Согласно настройкам в Railway: trolley.proxy.rlwy.net:50647
PG_CONNECTION_STRING = "postgresql://postgres:nQBxTlmgJmYiFLfSYNeDMGWarRHUkweS@trolley.proxy.rlwy.net:50647/railway"
logger.info("Используем явный URL для подключения к PostgreSQL")

# Запасной вариант - попробуем использовать переменные окружения, если доступны
DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_PUBLIC_URL = os.getenv('DATABASE_PUBLIC_URL')

# Если есть DATABASE_PUBLIC_URL, используем его
if DATABASE_PUBLIC_URL and DATABASE_PUBLIC_URL != "None" and DATABASE_PUBLIC_URL != "":
    PG_CONNECTION_STRING = DATABASE_PUBLIC_URL
    logger.info("Используем DATABASE_PUBLIC_URL для подключения к PostgreSQL")
# Если есть DATABASE_URL, используем его
elif DATABASE_URL and DATABASE_URL != "None" and DATABASE_URL != "":
    PG_CONNECTION_STRING = DATABASE_URL
    logger.info("Используем DATABASE_URL для подключения к PostgreSQL")

# Глобальный пул соединений
_pool = None

async def get_pool():
    """Получить пул соединений с базой данных."""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(PG_CONNECTION_STRING, min_size=2, max_size=10)
            logger.info(f"Создан пул соединений с базой данных PostgreSQL")
        except Exception as e:
            logger.error(f"Ошибка при создании пула соединений с PostgreSQL: {e}")
            raise
    return _pool

async def init_db():
    """Инициализировать базу данных и создать необходимые таблицы."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
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
                
                CREATE INDEX IF NOT EXISTS idx_users_user_id ON users (user_id);
            ''')
        logger.info("База данных PostgreSQL инициализирована")
        return True
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных PostgreSQL: {e}")
        return False

async def get_user_balance(user_id):
    """Асинхронно получить баланс пользователя."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            balance = await conn.fetchval('SELECT balance FROM users WHERE user_id = $1', user_id)
            return balance if balance is not None else 0
    except Exception as e:
        logger.error(f"Ошибка при получении баланса пользователя {user_id}: {e}")
        return 0

async def check_balance_sufficient(user_id, cost=1):
    """Асинхронно проверить, достаточно ли у пользователя средств."""
    try:
        balance = await get_user_balance(user_id)
        return balance >= cost
    except Exception as e:
        logger.error(f"Ошибка при проверке баланса пользователя {user_id}: {e}")
        return False

async def create_user(user_id, username=None, first_name=None, last_name=None):
    """Асинхронно создать нового пользователя."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Проверяем, существует ли пользователь
            exists = await conn.fetchval('SELECT COUNT(1) FROM users WHERE user_id = $1', user_id)
            
            if exists:
                # Обновляем данные существующего пользователя
                await conn.execute('''
                    UPDATE users 
                    SET username = $2, first_name = $3, last_name = $4
                    WHERE user_id = $1
                ''', user_id, username or "", first_name or "", last_name or "")
                logger.info(f"Обновлены данные пользователя: {user_id}")
                return False  # Пользователь не был создан, просто обновлен
            else:
                # Создаем нового пользователя с начальным балансом 10 звезд
                await conn.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, balance)
                    VALUES ($1, $2, $3, $4, 10)
                ''', user_id, username or "", first_name or "", last_name or "")
                logger.info(f"Создан новый пользователь: {user_id}")
                return True  # Пользователь был создан
    except Exception as e:
        logger.error(f"Ошибка при создании/обновлении пользователя {user_id}: {e}")
        return False

async def update_user_balance(user_id, amount):
    """
    Асинхронно обновить баланс пользователя.
    
    Args:
        user_id: ID пользователя Telegram
        amount: Сумма для добавления (положительное число) или списания (отрицательное число)
    
    Returns:
        int: Новый баланс пользователя
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Проверяем, существует ли пользователь
            user_exists = await conn.fetchval('SELECT COUNT(1) FROM users WHERE user_id = $1', user_id)
            
            if not user_exists:
                # Если пользователь не существует, создаем его с начальным балансом равным amount
                await create_user(user_id)
                
                # Устанавливаем баланс равным amount (но не меньше 0)
                new_balance = max(0, amount)
                await conn.execute(
                    'UPDATE users SET balance = $2 WHERE user_id = $1',
                    user_id, new_balance
                )
            else:
                # Получаем текущий баланс
                current_balance = await get_user_balance(user_id)
                
                # Рассчитываем новый баланс (не меньше 0)
                new_balance = max(0, current_balance + amount)
                
                # Обновляем баланс и время последней операции
                await conn.execute('''
                    UPDATE users 
                    SET balance = $2, last_generation = CURRENT_TIMESTAMP
                    WHERE user_id = $1
                ''', user_id, new_balance)
                
                # Если это списание звезд за генерацию, увеличиваем счетчик генераций
                if amount < 0:
                    await conn.execute('''
                        UPDATE users
                        SET total_generations = total_generations + 1
                        WHERE user_id = $1
                    ''', user_id)
            
            logger.info(f"Обновлен баланс пользователя {user_id}: {'+' if amount > 0 else ''}{amount} звезд")
            return new_balance
    except Exception as e:
        logger.error(f"Ошибка при обновлении баланса пользователя {user_id}: {e}")
        # В случае ошибки возвращаем текущий баланс без изменений
        return await get_user_balance(user_id)

async def get_user_stats():
    """Асинхронно получить статистику по пользователям."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            stats = await conn.fetch('''
                SELECT 
                    COUNT(1) as total_users,
                    SUM(total_generations) as total_generations,
                    AVG(balance) as avg_balance
                FROM users
            ''')
            
            return {
                'total_users': stats[0]['total_users'] or 0,
                'total_generations': stats[0]['total_generations'] or 0,
                'avg_balance': round(stats[0]['avg_balance'] or 0, 2)
            }
    except Exception as e:
        logger.error(f"Ошибка при получении статистики пользователей: {e}")
        return {
            'total_users': 0,
            'total_generations': 0,
            'avg_balance': 0
        }

async def close_pool():
    """Закрыть пул соединений с базой данных."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Пул соединений с PostgreSQL закрыт")
