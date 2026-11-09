#!/usr/bin/env python3
"""Генерирует frontend/assets/js/i18n-dict.js из накопленных переводов.

Источники:
  * work/translations.jsonl — пары (es, ru, en) видимых строк интерфейса;
  * PATTERNS ниже — шаблоны для строк с подстановками (даты, счётчики, свежесть).

Словарь намеренно построен как «испанский оригинал → перевод», а не как ключи:
так перевод ложится поверх уже работающего кода без переписывания шаблонов, а
покрытие можно измерить (см. scripts/check_i18n_coverage.js).

Правило продукта (§02): интерфейс для Парагвая остаётся испанским, es — язык по
умолчанию. Русский и английский — языки просмотра для команды и партнёров;
названия компаний, брендов, баррио и адреса не переводятся, потому что это данные
продавцов, а не текст платформы.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "frontend" / "i18n" / "translations.jsonl"
OUT = ROOT / "frontend" / "assets" / "js" / "i18n-dict.js"

#: (регулярное выражение, замена для ru, замена для en)
PATTERNS: list[tuple[str, str, str]] = [
    (r"^Hoy: (.+)$", r"Сегодня: $1", r"Today: $1"),
    # по-русски счётчик читаем как подписи («карточек: 3»), иначе при единице
    # получалось «1 показов записано»
    (r"^(\d+) fichas · (\d+) impresiones registradas$", r"карточек: $1 · записано показов: $2", r"$1 listings · $2 impressions recorded"),
    (r"^(\d+) en publicidad$", r"$1 в рекламе", r"$1 in advertising"),
    (r"^(\d+) impresiones registradas$", r"записано показов: $1", r"$1 impressions recorded"),
    (r"^(\d+) fichas$", r"карточек: $1", r"$1 listings"),
    (r"^(\d+) ficha$", r"$1 карточка", r"$1 listing"),
    (r"^Página (\d+) de (\d+)$", r"Страница $1 из $2", r"Page $1 of $2"),
    (r"^(\d+) sucursales$", r"$1 филиала", r"$1 branches"),
    (r"^(\d+) ofertas activas$", r"$1 активных предложения", r"$1 active offers"),
    (r"^\(verificado hace (.+)\)$", r"(подтверждено $1 назад)", r"(verified $1 ago)"),
    (r"^Datos observados hace (.+) · fuente: (.+)$", r"Данные получены $1 назад · источник: $2", r"Data observed $1 ago · source: $2"),
    (r"^SKU (.+?) · observado hace (.+?) · válido hasta (.+?) · fuente: (.+)$",
     r"SKU $1 · наблюдалось $2 назад · действительно до $3 · источник: $4",
     r"SKU $1 · observed $2 ago · valid until $3 · source: $4"),
    (r"^Actualizada hace (.+)$", r"Обновлено $1 назад", r"Updated $1 ago"),
    (r"^hace (\d+) días$", r"$1 дн. назад", r"$1 days ago"),
    (r"^hace (\d+) h$", r"$1 ч назад", r"$1 h ago"),
    (r"^hace (\d+) min$", r"$1 мин назад", r"$1 min ago"),
    (r"^hace (.+)$", r"$1 назад", r"$1 ago"),
    (r"^Marca: (.+)$", r"Бренд: $1", r"Brand: $1"),
    (r"^Cuándo lo necesitás: (.+)$", r"Когда нужно: $1", r"When needed: $1"),
    (r"^Tu mensaje: «(.+)»$", r"Ваше сообщение: «$1»", r"Your message: “$1”"),
    (r"^Nota: (.+)$", r"Примечание: $1", r"Note: $1"),
    (r"^· comprobante (.+)$", r"· чек $1", r"· receipt $1"),
    (r"^Solicitud entregada: (.+)$", r"Заявка передана: $1", r"Request delivered: $1"),
    (r"^Confirmada: (.+)$", r"Подтверждена: $1", r"Confirmed: $1"),
    (r"^Entorno de demostración: (.+)$", r"Демонстрационное окружение: $1", r"Demo environment: $1"),
    (r"^No se pudo cargar la búsqueda: (.+)$", r"Не удалось загрузить поиск: $1", r"Could not load the search: $1"),
    (r"^No se pudo cargar: (.+)$", r"Не удалось загрузить: $1", r"Could not load: $1"),
    (r"^válido hasta (.+)$", r"действительно до $1", r"valid until $1"),
    (r"^observado hace (.+)$", r"наблюдалось $1 назад", r"observed $1 ago"),
    (r"^fuente: (.+)$", r"источник: $1", r"source: $1"),
    (r"^Persona jurídica: (.+)$", r"Юридическое лицо: $1", r"Legal entity: $1"),
    (r"^Los datos del catálogo local son ficticios y sirven para validar el recorrido; no son ofertas reales ni socios contratados\. Fichas publicadas en este entorno: (\d+)\. Personas jurídicas en el registro: (\d+) \(no son fichas\)\.$",
     r"Данные локального каталога вымышлены и служат для проверки пути; это не реальные предложения и не подписанные партнёры. Карточек опубликовано в этом окружении: $1. Юридических лиц в реестре: $2 (это не карточки).",
     r"Local catalog data is fictional and exists to validate the journey; these are not real offers or contracted partners. Listings published in this environment: $1. Legal entities in the registry: $2 (they are not listings)."),
    (r"^Fichas publicadas en este entorno: (\d+)\. Personas jurídicas en el registro: (\d+) \(no son fichas\)\.$",
     r"Карточек в этом окружении: $1. Юридических лиц в реестре: $2 (это не карточки).",
     r"Listings published in this environment: $1. Legal entities in the registry: $2 (they are not listings)."),
    (r"^(\d+) (\d+) fichas · (\d+) impresiones registradas$", r"карточек: $2 · записано показов: $3", r"$2 listings · $3 impressions recorded"),
    (r"^Estado de la ficha$", r"Статус карточки", r"Listing status"),
    (r"^(.+) · PRTDS$", r"$1 · PRTDS", r"$1 · PRTDS"),
]

#: месяцы и обозначения времени — переводятся внутри дат
DATE_BITS = {
    "ru": {
        "ene.": "янв.", "feb.": "февр.", "mar.": "мар.", "abr.": "апр.", "may.": "мая",
        "jun.": "июн.", "jul.": "июл.", "ago.": "авг.", "sep.": "сент.", "oct.": "окт.",
        "nov.": "нояб.", "dic.": "дек.", "a. m.": "ДП", "p. m.": "ПП",
    },
    "en": {
        "ene.": "Jan", "feb.": "Feb", "mar.": "Mar", "abr.": "Apr", "may.": "May",
        "jun.": "Jun", "jul.": "Jul", "ago.": "Aug", "sep.": "Sep", "oct.": "Oct",
        "nov.": "Nov", "dic.": "Dec", "a. m.": "AM", "p. m.": "PM",
    },
}


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    entries: dict[str, dict[str, str]] = {}
    if WORK.exists():
        for line in WORK.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entries[row["es"]] = {"ru": row["ru"], "en": row["en"]}
    else:
        print(f"нет файла переводов: {WORK}", file=sys.stderr)
        return 1

    ru = {es: pair["ru"] for es, pair in entries.items() if pair["ru"] != es}
    en = {es: pair["en"] for es, pair in entries.items() if pair["en"] != es}

    lines = [
        "/* Словарь переводов интерфейса. Сгенерирован scripts/build_i18n_dict.py —",
        " * не править вручную: изменения вносятся в источник переводов и пересобираются.",
        " *",
        " * Ключ — испанский оригинал строки, как она отрисована в DOM. Такой подход",
        " * позволяет переводить уже работающий интерфейс без переписывания шаблонов",
        " * и измерять покрытие (scripts/check_i18n_coverage.js).",
        " *",
        " * Не переводятся: названия компаний, брендов, баррио, адреса, телефоны, SKU,",
        " * номера обращений и коды событий — это данные продавцов и идентификаторы.",
        " */",
        "",
        f"export const RU = {{"
    ]
    for source, target in sorted(ru.items()):
        lines.append(f"  {js_string(source)}: {js_string(target)},")
    lines.append("};")
    lines.append("")
    lines.append("export const EN = {")
    for source, target in sorted(en.items()):
        lines.append(f"  {js_string(source)}: {js_string(target)},")
    lines.append("};")
    lines.append("")
    lines.append("/* Шаблоны для строк с подстановками: [регулярное выражение, ru, en]. */")
    lines.append("export const PATTERNS = [")
    for pattern, target_ru, target_en in PATTERNS:
        lines.append(f"  [{js_string(pattern)}, {js_string(target_ru)}, {js_string(target_en)}],")
    lines.append("];")
    lines.append("")
    lines.append("/* Обозначения месяцев и времени внутри дат. */")
    lines.append(f"export const DATE_BITS = {json.dumps(DATE_BITS, ensure_ascii=False, indent=2)};")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT}: ru {len(ru)} строк · en {len(en)} строк · шаблонов {len(PATTERNS)}")
    print(f"размер: {OUT.stat().st_size / 1024:.0f} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
