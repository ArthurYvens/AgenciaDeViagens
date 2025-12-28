from __future__ import annotations
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ========= Datas =========

def br_to_iso(date_str: str) -> str:
    s = (date_str or "").strip()
    dt = datetime.strptime(s, "%d/%m/%Y")
    return dt.strftime("%Y-%m-%d")

def iso_to_br(date_str: Optional[str]) -> str:
    if not date_str:
        return ""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")

# -------- Moeda ---------

def parse_currency_to_cents(value: Optional[str]) -> int:
    """Converte string de moeda BR/US para centavos (int).
    Aceita:
      - 'R$ 1.234,56', '1.234.567,89', '1,234,567.89'
      - negativos: '-R$ 1.234,56', 'R$ -1.234,56', '1.234,56-', '(1.234,56)'
    Retorna 0 para vazio/None.
    """
    if value is None:
        return 0

    s = str(value).strip()
    if s == "":
        return 0

    # sinal por parênteses
    negative = False
    if "(" in s and ")" in s:
        negative = True
        s = s.replace("(", "").replace(")", "")

    # remove prefixos e espaços (inclui NBSP)
    s = s.replace("R$", "").replace("\xa0", " ").strip()

    # sinal na frente/atrás
    if s.startswith("-"):
        negative = True
        s = s[1:].strip()
    if s.endswith("-"):
        negative = True
        s = s[:-1].strip()
    if s.startswith("+"):
        s = s[1:].strip()

    # mantém só dígitos e separadores
    allowed = set("0123456789.,")
    s = "".join(ch for ch in s if ch in allowed)

    # heurística de separador decimal quando há '.' e ','
    if "." in s and "," in s:
        last_dot = s.rfind(".")
        last_com = s.rfind(",")
        # último separador é o decimal
        if last_com > last_dot:
            # decimal = ',', pontos são milhares
            s = s.replace(".", "")
            s = s.replace(",", ".")
        else:
            # decimal = '.', vírgulas são milhares
            s = s.replace(",", "")
            # '.' já é decimal
    else:
        # único separador → vírgula como decimal BR
        if "," in s:
            s = s.replace(".", "")  # se houver, considere '.' como milhar
            s = s.replace(",", ".")
        # se só '.', já é decimal
        # se nenhum, é inteiro

    try:
        dec = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError("Formato de valor inválido") from exc

    if negative:
        dec = -dec

    # arredonda para centavos
    return int((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))



def format_cents_br(cents: Optional[int]) -> str:
    if cents is None:
        cents = 0
    negative = cents < 0
    cents = abs(int(cents))
    reais = cents // 100
    centavos = cents % 100
    reais_str = f"{reais:,}".replace(",", ".")
    txt = f"R$ {reais_str},{centavos:02d}"
    return f"-{txt}" if negative else txt

# -------- CPF ---------

def somente_digitos(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _calc_digito(nums: str) -> str:
    s = sum(int(d) * w for d, w in zip(nums, range(len(nums) + 1, 1, -1)))
    r = 11 - (s % 11)
    return "0" if r >= 10 else str(r)

def valido_cpf(cpf: str) -> bool:
    cpf = somente_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    d1 = _calc_digito(cpf[:9])
    d2 = _calc_digito(cpf[:9] + d1)
    return cpf[-2:] == d1 + d2

# --------- Outros ---------

def compute_lucro_cents_from_strings(
    venda_str: str, pago_str: Optional[str]
) -> Optional[int]:
    """Lucro em centavos (= pago - venda). Pode ser negativo."""
    try:
        venda = parse_currency_to_cents(venda_str)
    except Exception:
        return None

    if not pago_str or pago_str.strip() == "":
        pago = 0
    else:
        try:
            pago = parse_currency_to_cents(pago_str)
        except Exception:
            return None

    return pago - venda