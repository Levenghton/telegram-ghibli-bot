"""
Модуль утилит для логирования и измерения производительности.
"""
import time
import logging
import json
from typing import Dict, Any, Optional
from db import add_background_task

# Настройка логирования
logger = logging.getLogger(__name__)

def log_user_action(user_id: int, action: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Логирует действие пользователя в фоновом режиме.
    
    Args:
        user_id: ID пользователя
        action: Название действия (команды, нажатие кнопки и т.д.)
        details: Дополнительные данные о действии
    """
    try:
        # Подготавливаем данные для фоновой задачи
        task_data = {
            "user_id": user_id,
            "action": action,
            "details": details or {}
        }
        
        # Добавляем задачу в очередь для фоновой обработки
        add_background_task("log_action", task_data)
    except Exception as e:
        # В случае ошибки просто записываем в журнал и продолжаем
        logger.error(f"Ошибка при логировании действия пользователя: {e}")

def update_bot_stat(stat_name: str) -> None:
    """
    Увеличивает счетчик статистики бота в фоновом режиме.
    
    Args:
        stat_name: Название счетчика статистики
    """
    try:
        # Добавляем задачу в очередь для фоновой обработки
        add_background_task("update_stats", {"stat_name": stat_name})
    except Exception as e:
        # В случае ошибки просто записываем в журнал и продолжаем
        logger.error(f"Ошибка при обновлении статистики бота: {e}")

class PerformanceTimer:
    """
    Класс для измерения времени выполнения операций.
    Используется как контекстный менеджер (with).
    """
    
    def __init__(self, operation_name: str, user_id: Optional[int] = None):
        """
        Инициализация таймера.
        
        Args:
            operation_name: Название операции
            user_id: ID пользователя (необязательно)
        """
        self.operation_name = operation_name
        self.user_id = user_id
        self.start_time = None
        
    def __enter__(self):
        """Начало контекста, запуск таймера."""
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Завершение контекста, остановка таймера и логирование.
        
        Args:
            exc_type: Тип исключения (если было)
            exc_val: Значение исключения
            exc_tb: Трассировка исключения
        """
        elapsed_ms = (time.time() - self.start_time) * 1000
        
        if exc_type:
            # Если была ошибка
            error_msg = f"{exc_type.__name__}: {exc_val}"
            logger.error(f"Операция '{self.operation_name}' завершилась с ошибкой за {elapsed_ms:.2f} мс: {error_msg}")
        else:
            # Успешное завершение
            logger.info(f"Операция '{self.operation_name}' выполнена за {elapsed_ms:.2f} мс")
            
            # Дополнительно логируем как действие пользователя, если указан user_id
            if self.user_id:
                log_user_action(
                    self.user_id,
                    f"performance:{self.operation_name}",
                    {"execution_time_ms": round(elapsed_ms, 2)}
                )
