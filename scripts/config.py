"""Parâmetros fixos da busca de passagens GYN -> FLN."""

ORIGIN_CODE = "GYN"
ORIGIN_CITY = "Goiânia"
DEST_CODE = "FLN"
DEST_CITY = "Florianópolis"

DEPART_DATE = "2026-11-26"  # YYYY-MM-DD
RETURN_DATE = "2026-11-30"  # YYYY-MM-DD

ADULTS = 2

GOAL_PRICE_PER_ADULT = 800.0

CSV_PATH = "historico_precos.csv"
SUMMARY_PATH = "resumo.md"

CSV_HEADER = [
    "data_consulta",
    "horario_consulta",
    "preco_por_adulto",
    "preco_total_2_adultos",
    "companhia_voo",
    "fonte",
    "link",
    "observacoes",
]
