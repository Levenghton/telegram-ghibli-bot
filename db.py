"""
Модуль для асинхронной работы с базой данных PostgreSQL.
"""
import os
import logging
import asyncio
import asyncpg
import time
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, Any, Optional

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logger = logging.getLogger(__name__)

# Очередь для фоновых задач с БД
background_tasks = asyncio.Queue()

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

# Глобальные переменные
_pool = None
_background_worker_task = None

# Структуры для кэширования
# Кэш данных пользователей {user_id: {"balance": value, "last_updated": timestamp, ...}}
user_cache: Dict[int, Dict[str, Any]] = {}

# Максимальное время жизни записи в кэше (в секундах)
CACHE_TTL = 300  # 5 минут

def get_from_cache(user_id: int, key: str) -> Optional[Any]:
    """Получить значение из кэша по идентификатору пользователя и ключу"""
    if user_id in user_cache and key in user_cache[user_id]:
        # Проверяем актуальность данных
        if time.time() - user_cache[user_id].get('last_updated', 0) < CACHE_TTL:
            return user_cache[user_id][key]
    return None

def update_cache(user_id: int, key: str, value: Any) -> None:
    """Обновить значение в кэше"""
    if user_id not in user_cache:
        user_cache[user_id] = {}
    user_cache[user_id][key] = value
    user_cache[user_id]['last_updated'] = time.time()

def invalidate_cache(user_id: int) -> None:
    """Инвалидировать кэш пользователя"""
    if user_id in user_cache:
        del user_cache[user_id]

async def get_pool():
    """Получить пул соединений с базой данных."""
    global _pool
    if _pool is None:
        try:
            # Оптимизированные настройки для высокой нагрузки
            _pool = await asyncpg.create_pool(
                PG_CONNECTION_STRING, 
                min_size=5,       # Увеличиваем минимальное количество соединений для обслуживания большего количества пользователей
                max_size=20,      # Увеличиваем максимум для большего параллелизма
                command_timeout=5,   # Уменьшаем таймаут, чтобы не блокировать соединения надолго
                max_inactive_connection_lifetime=60,  # Дольше держим соединения для сокращения накладных расходов
                server_settings={'application_name': 'telegram-ghibli-bot'}  # Добавляем идентификацию приложения
            )
            logger.info(f"Создан оптимизированный пул соединений с базой данных PostgreSQL")
        except Exception as e:
            logger.error(f"Ошибка при создании пула соединений с PostgreSQL: {e}")
            raise
    return _pool

async def init_db():
    """Инициализировать базу данных и создать необходимые таблицы."""
    try:
        # Создаем пул соединений, если его еще нет
        pool = await get_pool()
        
        async with pool.acquire() as conn:
            # Создаем таблицу пользователей, если ее нет
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_generation TIMESTAMP,
                    total_generations INTEGER DEFAULT 0
                )
            ''')
            
            # Создаем таблицу для истории изменений баланса
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS balance_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    amount INTEGER NOT NULL,
                    operation_type TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Создаем таблицу для логирования действий пользователей (для фоновых задач)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_actions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    action TEXT NOT NULL,
                    details JSONB,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Создаем таблицу для статистики бота
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_stats (
                    stat_name TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            logger.info("\u0411аза данных успешно инициализирована")
            
        # Запускаем обработчик фоновых задач
        await start_background_worker()
        logger.info("Запущен обработчик фоновых задач")
        
        # Возвращаем True в случае успеха для совместимости с основным кодом
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        return False

async def get_user_balance(user_id):
    """Асинхронно получить баланс пользователя с использованием кэша."""
    # Сначала проверяем кэш
    cached_balance = get_from_cache(user_id, 'balance')
    if cached_balance is not None:
        return cached_balance
        
    # Если данных нет в кэше, запрашиваем из БД
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            query = "SELECT balance FROM users WHERE user_id = $1"
            row = await connection.fetchrow(query, user_id)
            balance = row['balance'] if row else 0
            
            # Кэшируем полученное значение
            update_cache(user_id, 'balance', balance)
            return balance
    except Exception as e:
        logger.error(f"Ошибка при получении баланса пользователя {user_id}: {e}")
        return 0

async def check_balance_sufficient(user_id, cost=1):
    """Асинхронно проверить, достаточно ли у пользователя средств.
    Использует оптимизированную функцию get_user_balance с кэшированием."""
    try:
        # Сразу используем кэшированную функцию get_user_balance
        balance = await get_user_balance(user_id)
        return balance >= cost
    except Exception as e:
        logger.error(f"Ошибка при проверке баланса пользователя {user_id}: {e}")
        return False

async def create_user(user_id, username=None, first_name=None, last_name=None):
    """Асинхронно создать нового пользователя с обновлением кэша."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Проверяем, существует ли пользователь
            user_exists = await conn.fetchval('SELECT COUNT(1) FROM users WHERE user_id = $1', user_id)
            
            if not user_exists:
                # Создаем нового пользователя с начальным балансом 10 звезд
                # (1 звезда - стандартный бонус, это позволит пользователю сразу попробовать сервис)
                initial_balance = 10
                
                await conn.execute('''
                    INSERT INTO users(user_id, username, first_name, last_name, balance, created_at, updated_at, total_generations) 
                    VALUES($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)
                ''', user_id, username, first_name, last_name, initial_balance)
                
                # Кэшируем баланс нового пользователя
                update_cache(user_id, 'balance', initial_balance)
                
                logger.info(f"Создан новый пользователь {user_id} {username} {first_name} {last_name} с балансом {initial_balance} звезд")
                
                # Добавляем запись в историю баланса
                await conn.execute('''
                    INSERT INTO balance_history(user_id, amount, operation_type, timestamp)
                    VALUES($1, $2, 'initial', CURRENT_TIMESTAMP)
                ''', user_id, initial_balance)
                
                return initial_balance
            else:
                # Пользователь уже существует, обновляем данные
                await conn.execute('''
                    UPDATE users 
                    SET username = $2, first_name = $3, last_name = $4, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = $1
                ''', user_id, username, first_name, last_name)
                
                logger.info(f"Обновлены данные пользователя {user_id} {username} {first_name} {last_name}")
                
                # Используем кэшированную функцию для получения баланса
                return await get_user_balance(user_id)
    except Exception as e:
        logger.error(f"Ошибка при создании/обновлении пользователя {user_id}: {e}")
        # Инвалидируем кэш в случае ошибки
        invalidate_cache(user_id)
        return 0

async def update_user_balance(user_id, amount):
    """
    Асинхронно обновить баланс пользователя с обновлением кэша.
    
    Args:
        user_id: ID пользователя Telegram
        amount: Сумма для добавления (положительное число) или списания (отрицательное число)
    
    Returns:
        int: Новый баланс пользователя
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            # Используем транзакцию для обеспечения атомарности операции
            async with connection.transaction():
                # Получаем текущий баланс (не используем кэш для надежности)
                current_balance_query = "SELECT balance FROM users WHERE user_id = $1"
                row = await connection.fetchrow(current_balance_query, user_id)
                
                if row:
                    # Пользователь существует - обновляем баланс
                    current_balance = row['balance']
                    new_balance = current_balance + amount
                    
                    # Обновляем запись в базе данных
                    update_query = """
                    UPDATE users 
                    SET balance = $1, updated_at = $2
                    WHERE user_id = $3
                    """
                    await connection.execute(update_query, new_balance, datetime.now(), user_id)
                    
                    # Обновляем значение в кэше
                    update_cache(user_id, 'balance', new_balance)
                    
                    # Логируем транзакцию
                    log_query = """
                    INSERT INTO balance_history (user_id, amount, operation_type, timestamp)
                    VALUES ($1, $2, $3, $4)
                    """
                    operation_type = "add" if amount > 0 else "subtract"
                    await connection.execute(log_query, user_id, abs(amount), operation_type, datetime.now())
                    
                    return new_balance
                else:
                    # Такого не должно быть, так как мы создаем пользователя при первом взаимодействии
                    logger.error(f"Попытка обновить баланс для несуществующего пользователя: {user_id}")
                    return 0
    except Exception as e:
        logger.error(f"Ошибка при обновлении баланса пользователя {user_id}: {e}")
        # Инвалидируем кэш в случае ошибки
        invalidate_cache(user_id)
        return await get_user_balance(user_id)  # Возвращаем текущий баланс в случае ошибки

async def get_user(user_id):
    """Асинхронно получить данные пользователя по user_id."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
            return user
    except Exception as e:
        logger.error(f"Ошибка при получении данных пользователя {user_id}: {e}")
        return None

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

async def process_background_tasks():
    """Обработчик фоновых задач для базы данных.
    Выполняет некритичные операции в фоновом режиме, не блокируя основной поток.
    """
    try:
        logger.info("Запущен обработчик фоновых задач с БД")
        while True:
            try:
                # Ждем новую задачу из очереди
                task = await background_tasks.get()
                task_type, data = task
                
                # Получаем пул соединений
                pool = await get_pool()
                
                # Обрабатываем задачу в зависимости от типа
                if task_type == "log_action":
                    # Логирование действия пользователя
                    user_id = data.get("user_id")
                    action = data.get("action")
                    details = data.get("details")
                    
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO user_actions (user_id, action, details, timestamp) VALUES ($1, $2, $3, $4)",
                            user_id, action, details, datetime.now()
                        )
                        logger.debug(f"Залогировано действие пользователя {user_id}: {action}")
                        
                elif task_type == "update_stats":
                    # Обновление статистики
                    async with pool.acquire() as conn:
                        # Обновляем статистику
                        await conn.execute(
                            "UPDATE bot_stats SET value = value + 1 WHERE stat_name = $1",
                            data.get("stat_name")
                        )
                        logger.debug(f"Обновлена статистика: {data.get('stat_name')}")
                
                # Отметить задачу как выполненную
                background_tasks.task_done()
                
            except Exception as e:
                logger.error(f"Ошибка при обработке фоновой задачи: {e}")
                # Не прерываем цикл при ошибке
    except asyncio.CancelledError:
        logger.info("Обработчик фоновых задач остановлен")


def add_background_task(task_type, data):
    """Добавить задачу в очередь фоновых задач.
    
    Args:
        task_type (str): Тип задачи ("log_action", "update_stats" и т.д.)
        data (dict): Данные для задачи
    """
    try:
        # Добавляем задачу в очередь, не блокируя выполнение
        background_tasks.put_nowait((task_type, data))
        # logger.debug(f"Добавлена фоновая задача: {task_type}")
    except Exception as e:
        # Если не удалось добавить задачу, просто логируем ошибку
        logger.error(f"Ошибка при добавлении фоновой задачи: {e}")


async def start_background_worker():
    """Запустить обработчик фоновых задач."""
    global _background_worker_task
    
    # Если задача уже запущена и не завершена, не запускаем новую
    if _background_worker_task and not _background_worker_task.done():
        return
    
    # Создаем и запускаем новую задачу
    _background_worker_task = asyncio.create_task(process_background_tasks())
    # Игнорируем исключения, чтобы задача не вызывала ошибку при завершении
    _background_worker_task.add_done_callback(lambda _: None)


async def close_pool():
    """Закрыть пул соединений с базой данных."""
    global _pool, _background_worker_task
    
    # Останавливаем фоновую задачу, если она запущена
    if _background_worker_task and not _background_worker_task.done():
        _background_worker_task.cancel()
        try:
            await _background_worker_task
        except asyncio.CancelledError:
            pass
            
    # Закрываем пул соединений
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Пул соединений с базой данных закрыт")
