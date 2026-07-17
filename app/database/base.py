from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Declarative base class for all SQLAlchemy models.

    Every model in app/models/ must inherit from this Base.
    SQLAlchemy uses it to track the full registry of mapped tables,
    which is required for create_all() to work correctly.
    """
    pass
