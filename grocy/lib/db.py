"""
Database module for Grocy extension.

Provides Postgres connection and table management for macro tracking data.
All timestamps stored in UTC, displayed in America/New_York.
"""
import os
from typing import Any, Dict, List, Optional, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager


def get_db_connection_params() -> Dict[str, str]:
    """Get Postgres connection parameters from environment."""
    return {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': os.getenv('POSTGRES_PORT', '5432'),
        'database': os.getenv('POSTGRES_DB', 'luna'),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', ''),
    }


@contextmanager
def get_db():
    """Get database connection context manager."""
    conn = psycopg2.connect(**get_db_connection_params())
    try:
        yield conn
    finally:
        conn.close()


def init_schema():
    """Initialize database schema for Grocy extension."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Create temp_items table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grocy_temp_items (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    calories REAL,
                    carbs REAL,
                    fats REAL,
                    protein REAL,
                    day TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            
            # Create config table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grocy_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            # Insert default config values
            cur.execute("""
                INSERT INTO grocy_config (key, value)
                VALUES ('day_start_hour', '6')
                ON CONFLICT (key) DO NOTHING
            """)
            
            cur.execute("""
                INSERT INTO grocy_config (key, value)
                VALUES ('goal_calories', '3500')
                ON CONFLICT (key) DO NOTHING
            """)
            
            cur.execute("""
                INSERT INTO grocy_config (key, value)
                VALUES ('goal_carbs', '350')
                ON CONFLICT (key) DO NOTHING
            """)
            
            cur.execute("""
                INSERT INTO grocy_config (key, value)
                VALUES ('goal_fats', '100')
                ON CONFLICT (key) DO NOTHING
            """)
            
            cur.execute("""
                INSERT INTO grocy_config (key, value)
                VALUES ('goal_protein', '250')
                ON CONFLICT (key) DO NOTHING
            """)
            
            conn.commit()


def execute_query(sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
    """Execute a query and return results as list of dicts."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            results = cur.fetchall()
            return [dict(row) for row in results]


def execute_update(sql: str, params: Optional[Tuple] = None) -> int:
    """Execute an update/insert/delete and return affected rows or last id."""
    with get_db() as conn:
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            conn.commit()
            
            # For INSERT, try to get the returned ID
            if sql.strip().upper().startswith('INSERT'):
                try:
                    return cur.fetchone()[0] if cur.description else cur.rowcount
                except (TypeError, IndexError):
                    return cur.rowcount
            return cur.rowcount


# Initialize schema on module load
try:
    init_schema()
except Exception as e:
    print(f"Warning: Could not initialize Grocy database schema: {e}")




