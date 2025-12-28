from __future__ import annotations
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

DEFAULT_DB_PATH = os.environ.get("TRAVELCRM_DB", "agencia_viagens.db")
DB_PATH = DEFAULT_DB_PATH

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.DatabaseError:
        pass
    return conn

def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_completo TEXT NOT NULL,
                data_nascimento TEXT NOT NULL,
                data_compra_voo TEXT NOT NULL,
                doc_tipo TEXT NOT NULL CHECK(doc_tipo IN ('CPF','Passaporte')),
                doc_valor TEXT NOT NULL,
                valor_venda_cents INTEGER NOT NULL,
                valor_lucro_cents INTEGER NOT NULL,
                valor_pago_cents INTEGER DEFAULT 0 NOT NULL,
                data_ida TEXT NOT NULL,
                data_volta TEXT,
                doc_voo_path TEXT,
                created_at TEXT DEFAULT (DATE('now')),
                updated_at TEXT DEFAULT (DATE('now'))
            );
            """
        )
        for col, ddl in [
            ("valor_pago_cents", "ALTER TABLE clientes ADD COLUMN valor_pago_cents INTEGER DEFAULT 0 NOT NULL;"),
            ("data_ida", "ALTER TABLE clientes ADD COLUMN data_ida TEXT NOT NULL DEFAULT DATE('now');"),
            ("data_volta", "ALTER TABLE clientes ADD COLUMN data_volta TEXT;"),
            ("doc_voo_path", "ALTER TABLE clientes ADD COLUMN doc_voo_path TEXT;"),
        ]:
            if not _column_exists(conn, "clientes", col):
                conn.execute(ddl)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_data_compra ON clientes (data_compra_voo);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_nome ON clientes (nome_completo);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clientes_data_ida ON clientes (data_ida);")

def insert_cliente(data: Dict[str, object]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO clientes (
                nome_completo, data_nascimento, data_compra_voo, doc_tipo, doc_valor,
                valor_venda_cents, valor_lucro_cents, valor_pago_cents,
                data_ida, data_volta, doc_voo_path, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?, DATE('now'))
            """,
            (
                data["nome_completo"],
                data["data_nascimento"],
                data["data_compra_voo"],
                data["doc_tipo"],
                data["doc_valor"],
                data["valor_venda_cents"],
                data["valor_lucro_cents"],
                data.get("valor_pago_cents", 0),
                data["data_ida"],
                data.get("data_volta"),
                data.get("doc_voo_path"),
            ),
        )
        return cur.lastrowid

def update_cliente(cid: int, data: Dict[str, object]) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE clientes SET
                nome_completo=?, data_nascimento=?, data_compra_voo=?,
                doc_tipo=?, doc_valor=?, valor_venda_cents=?, valor_lucro_cents=?, valor_pago_cents=?,
                data_ida=?, data_volta=?, doc_voo_path=?,
                updated_at=DATE('now')
            WHERE id=?
            """,
            (
                data["nome_completo"],
                data["data_nascimento"],
                data["data_compra_voo"],
                data["doc_tipo"],
                data["doc_valor"],
                data["valor_venda_cents"],
                data["valor_lucro_cents"],
                data.get("valor_pago_cents", 0),
                data["data_ida"],
                data.get("data_volta"),
                data.get("doc_voo_path"),
                cid,
            ),
        )

def delete_cliente(cid: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM clientes WHERE id=?", (cid,))

def list_clientes(search: str = "") -> List[Tuple]:
    with get_conn() as conn:
        base_sql = """
            SELECT id, nome_completo, data_nascimento, data_compra_voo,
                   doc_tipo, doc_valor, valor_venda_cents, valor_lucro_cents, valor_pago_cents,
                   data_ida, data_volta, doc_voo_path
            FROM clientes
        """
        if search:
            like = f"%{search}%"
            cur = conn.execute(
                base_sql + " WHERE nome_completo LIKE ? OR doc_valor LIKE ? ORDER BY data_compra_voo DESC, id DESC",
                (like, like),
            )
        else:
            cur = conn.execute(base_sql + " ORDER BY data_compra_voo DESC, id DESC")
        return list(cur.fetchall())

def list_by_month_year(year: int, month: Optional[int]) -> List[Tuple]:
    with get_conn() as conn:
        if month:
            cur = conn.execute(
                """
                SELECT id, nome_completo, data_nascimento, data_compra_voo,
                       doc_tipo, doc_valor, valor_venda_cents, valor_lucro_cents, valor_pago_cents,
                       data_ida, data_volta, doc_voo_path
                FROM clientes
                WHERE strftime('%Y', data_compra_voo)=? AND strftime('%m', data_compra_voo)=?
                ORDER BY data_compra_voo DESC, id DESC
                """,
                (f"{year:04d}", f"{month:02d}"),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, nome_completo, data_nascimento, data_compra_voo,
                       doc_tipo, doc_valor, valor_venda_cents, valor_lucro_cents, valor_pago_cents,
                       data_ida, data_volta, doc_voo_path
                FROM clientes
                WHERE strftime('%Y', data_compra_voo)=?
                ORDER BY data_compra_voo DESC, id DESC
                """,
                (f"{year:04d}",),
            )
        return list(cur.fetchall())

def sum_lucro(year: Optional[int] = None, month: Optional[int] = None) -> int:
    with get_conn() as conn:
        if year and month:
            cur = conn.execute(
                "SELECT COALESCE(SUM(valor_lucro_cents),0) FROM clientes WHERE strftime('%Y', data_compra_voo)=? AND strftime('%m', data_compra_voo)=?",
                (f"{year:04d}", f"{month:02d}"),
            )
        elif year:
            cur = conn.execute(
                "SELECT COALESCE(SUM(valor_lucro_cents),0) FROM clientes WHERE strftime('%Y', data_compra_voo)=?",
                (f"{year:04d}",),
            )
        else:
            cur = conn.execute("SELECT COALESCE(SUM(valor_lucro_cents),0) FROM clientes")
        return int(cur.fetchone()[0])

def available_years() -> List[int]:
    import datetime as _dt
    with get_conn() as conn:
        cur = conn.execute("SELECT DISTINCT strftime('%Y', data_compra_voo) AS y FROM clientes ORDER BY y ASC")
        rows = [int(r[0]) for r in cur.fetchall() if r[0] is not None]
        if not rows:
            rows = [_dt.datetime.now().year]
        return rows

def flights_departing_on(target: "date") -> List[Tuple]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id, nome_completo, data_ida, data_volta, doc_tipo, doc_valor, doc_voo_path FROM clientes WHERE data_ida = ? ORDER BY id DESC",
            (target.strftime("%Y-%m-%d"),),
        )
        return list(cur.fetchall())
