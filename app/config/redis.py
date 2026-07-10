from arq.connections import RedisSettings

from app.config.settings import settings

redis_settings = RedisSettings(
    host=settings.redis_host,
    port=settings.redis_port,
)
