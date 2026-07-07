from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings
from app.utils.logger import logger

# Create the async engine
# pool_pre_ping=True: Tests the connection before using it (prevents "MySQL has gone away" style errors)
# pool_size & max_overflow: Controls connection pooling for high concurrency
try:
    engine = create_async_engine(
        settings.database_url,
        echo=False,  # Log SQL queries in dev mode
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
except Exception as e:
    logger.critical(f"Failed to initialize database engine: {e!s}")
    raise

# Create a session factory
# expire_on_commit=False is required for async SQLAlchemy so it doesn't try to auto-refresh objects synchronously
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    Dependency function for FastAPI routes.
    Yields a database session and safely closes it after the request completes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session rollback due to error: {e!s}")
            raise
        finally:
            await session.close()
