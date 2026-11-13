#!/usr/bin/env python3
"""Відтворювано створює вигадані демонстраційні таблиці для меблевої студії.

⚠️ Усі клієнти, телефони, суми й дати вигадані. Це не реальні дані студії.
Телефони мають код оператора «00» (+380 00 ...), якого не існує, тому
жоден номер не може збігтися з реальним.

Початкові вимоги походять з навчальної вправи; параметри генерації уточнені
для цього проєкту. Вихідні CSV:
  zayavky_olena.csv
  zayavky_igor.csv
  zayavky_maryna.csv

Відтворюваність: усі випадкові значення беруться з одного
random.Random(seed); поточна дата і час не використовуються; порядок
обходу — тільки списки (не множини). Той самий seed і та сама версія
скрипту дають побайтово однакові файли.

Порядок роботи: згенерувати -> відформатувати -> перевірити специфікацію,
розбираючи вже відформатовані рядки -> лише тоді записати файли.
Наявні файли не перезаписуються без прапорця --force.

Тільки стандартна бібліотека Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import re
import sys
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

DEFAULT_SEED = 20261102
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data"

# Звітний період, узгоджений у brief.md для демонстраційного набору
REPORT_DATE = date(2026, 11, 2)
WEEK_START = date(2026, 10, 26)
WEEK_END = date(2026, 11, 1)
MONTH_START = date(2026, 10, 1)
PRE_WEEK_LAST = WEEK_START - timedelta(days=1)  # 25.10.2026

N_LEADS = 25  # «25 заявок» у кожного менеджера

# Єдині (канонічні) етапи
NEW, CALC, MEASURE, CONTRACT, REFUSAL = "Нова", "Прорахунок", "Замір", "Договір", "Відмова"
OPEN_STAGES = [NEW, CALC, MEASURE]

PRODUCTS = ["кухня", "шафа-купе", "гардеробна", "дитяча кімната", "передпокій"]
# Діапазони сум у тисячах грн (умовні, для правдоподібності демо)
PRICE_K = {
    "кухня": (60, 180),
    "шафа-купе": (25, 70),
    "гардеробна": (40, 120),
    "дитяча кімната": (35, 90),
    "передпокій": (20, 50),
}

# Наступний крок у коментарі: «<дія> ДД.ММ»
STEP_ACTIONS = {
    NEW: ["передзвонити", "уточнити розміри"],
    CALC: ["надіслати прорахунок", "обговорити прорахунок"],
    MEASURE: ["виїхати на замір", "погодити проєкт після заміру"],
    CONTRACT: ["монтаж", "доставка і монтаж"],
    REFUSAL: ["нагадати про акцію"],
}

# Вигадані імена (поєднуються випадково)
SURNAMES = [
    "Коваль", "Мельник", "Шевчук", "Бондар", "Ткачук", "Кравець", "Олійник",
    "Лисенко", "Руденко", "Савчук", "Гнатюк", "Поліщук", "Марченко", "Левченко",
    "Кузьменко", "Павленко", "Остапчук", "Довгань", "Гуменюк", "Яковенко",
    "Федорук", "Мороз", "Білик", "Литвин", "Гончар", "Сидоренко", "Вовк", "Кушнір",
]
FIRST_M = ["Андрій", "Олег", "Дмитро", "Сергій", "Василь", "Тарас", "Богдан",
           "Максим", "Роман", "Юрій", "Віктор", "Остап"]
FIRST_F = ["Ірина", "Наталія", "Оксана", "Тетяна", "Юлія", "Світлана", "Галина",
           "Катерина", "Софія", "Леся", "Мар'яна", "Христина"]
# (чоловіча форма, жіноча форма) по батькові
PATRONYMICS = [
    ("Олександрович", "Олександрівна"), ("Петрович", "Петрівна"),
    ("Іванович", "Іванівна"), ("Миколайович", "Миколаївна"),
    ("Васильович", "Василівна"), ("Степанович", "Степанівна"),
    ("Григорович", "Григорівна"), ("Володимирович", "Володимирівна"),
]


@dataclass
class Lead:
    created: date
    first: str
    last: str
    patronymic: str
    phone: str
    source: str          # канонічний ключ джерела
    product: str
    amount_k: int | None  # тисячі грн; None — порожньо
    stage: str | None     # канонічний етап; None — порожньо
    step: str
    step_date: date
    forgotten: bool = False


@dataclass(frozen=True)
class ManagerSpec:
    key: str
    filename: str
    columns: list[str]
    sources: dict[str, str]   # канонічний ключ -> як пише менеджер
    stages: dict[str, str]    # канонічний етап -> як пише менеджер
    n_week: int
    n_forgotten: int


OLENA = ManagerSpec(
    key="olena",
    filename="zayavky_olena.csv",
    columns=["Дата", "Клієнт", "Телефон", "Джерело", "Що замовляє", "Сума", "Етап", "Коментар"],
    sources={"instagram": "Instagram", "telegram": "Telegram", "recommendation": "рекомендація",
             "maps": "Google Карти", "call": "дзвінок"},
    stages={NEW: "Нова", CALC: "Прорахунок", MEASURE: "Замір", CONTRACT: "Договір", REFUSAL: "Відмова"},
    n_week=9,       # «з них 9 за тиждень»
    n_forgotten=5,  # «У 5 заявках ... про цих клієнтів забули»
)
IGOR = ManagerSpec(
    key="igor",
    filename="zayavky_igor.csv",
    columns=["Коли", "Ім'я", "Тел.", "Звідки прийшов", "Виріб", "Бюджет", "Статус", "Нотатки"],
    sources={"instagram": "інста", "telegram": "тг", "recommendation": "по рекомендації",
             "maps": "карти", "call": "дзвонив"},
    stages={NEW: "новий", CALC: "рахую", MEASURE: "заміряли", CONTRACT: "підписали", REFUSAL: "злився"},
    n_week=8,       # «з них 8 за тиждень»
    n_forgotten=5,  # «4–6 клієнтів, про яких забули»
)
MARYNA = ManagerSpec(
    key="maryna",
    filename="zayavky_maryna.csv",
    columns=["дата_створення", "клієнт_піб", "телефон", "канал_залучення", "товар", "сума_грн",
             "стадія_угоди", "примітка"],
    sources={"instagram": "Instagram", "facebook": "Facebook", "google_ads": "Google Ads",
             "recommendation": "рекомендація", "call": "дзвінок"},
    stages={NEW: "НОВА", CALC: "РОЗРАХУНОК", MEASURE: "ЗАМІР", CONTRACT: "УГОДА", REFUSAL: "ВТРАЧЕНО"},
    n_week=10,      # «з них 10 за тиждень»
    n_forgotten=4,  # «У 4–6 заявках ... забули»
)
IGOR_EMPTY_BUDGETS = 3     # «суми ... або порожньо» — крім договору з порожньою сумою
MARYNA_DUPLICATES = 2      # «є 2–3 дублі рядків»
MARYNA_EMPTY_STAGES = 3    # «кілька порожніх стадій»

IGOR_MONTHS = {10: "жовт", 11: "лист"}


# ---------------------------------------------------------------- генерація

class Registry:
    """Стежить, щоб імена і телефони не повторювались між таблицями."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.names: set[tuple[str, str]] = set()
        self.phones: set[str] = set()

    def person(self) -> tuple[str, str, str]:
        while True:
            female = self.rng.random() < 0.5
            first = self.rng.choice(FIRST_F if female else FIRST_M)
            last = self.rng.choice(SURNAMES)
            patr = self.rng.choice(PATRONYMICS)[1 if female else 0]
            if (first, last) not in self.names:
                self.names.add((first, last))
                return first, last, patr

    def phone(self) -> str:
        while True:
            p = (f"+380 00 {self.rng.randint(100, 999)} "
                 f"{self.rng.randint(10, 99)} {self.rng.randint(10, 99)}")
            if p not in self.phones:
                self.phones.add(p)
                return p


def rand_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build_leads(rng: random.Random, reg: Registry, spec: ManagerSpec) -> list[Lead]:
    """25 заявок за жовтень 2026: n_week у звітному тижні, n_forgotten забутих."""
    dates = ([rand_date(rng, WEEK_START, WEEK_END) for _ in range(spec.n_week)]
             + [rand_date(rng, MONTH_START, PRE_WEEK_LAST) for _ in range(N_LEADS - spec.n_week)])
    dates.sort()

    leads = []
    for d in dates:
        first, last, patr = reg.person()
        product = rng.choice(PRODUCTS)
        leads.append(Lead(
            created=d, first=first, last=last, patronymic=patr, phone=reg.phone(),
            source=rng.choice(list(spec.sources)), product=product,
            amount_k=rng.randint(*PRICE_K[product]),
            stage=None, step="", step_date=d,
        ))

    # Забуті: етап відкритий, дата наступного кроку раніша за дату звіту.
    # Крок має бути пізніше за створення заявки, тому беремо заявки до 30.10.
    candidates = [i for i, l in enumerate(leads) if l.created <= WEEK_END - timedelta(days=2)]
    forgotten = rng.sample(candidates, spec.n_forgotten)
    rest = [i for i in range(N_LEADS) if i not in forgotten]
    n_contract, n_refusal = rng.randint(3, 5), rng.randint(2, 3)
    closed = rng.sample(rest, n_contract + n_refusal)
    contracts, refusals = closed[:n_contract], closed[n_contract:]

    for i, lead in enumerate(leads):
        if i in forgotten:
            lead.stage = rng.choice(OPEN_STAGES)
            lead.step_date = rand_date(rng, lead.created + timedelta(days=1), WEEK_END)
            lead.forgotten = True
        elif i in contracts:
            lead.stage = CONTRACT
            lead.step_date = rand_date(rng, REPORT_DATE + timedelta(days=7), REPORT_DATE + timedelta(days=28))
        elif i in refusals:
            lead.stage = REFUSAL
            lead.step_date = rand_date(rng, date(2026, 12, 1), date(2026, 12, 15))
        else:
            lead.stage = rng.choice(OPEN_STAGES)
            # Не забуті: крок не раніше дати звіту.
            lead.step_date = rand_date(rng, REPORT_DATE, REPORT_DATE + timedelta(days=12))
        lead.step = rng.choice(STEP_ACTIONS[lead.stage])
    return leads


def open_active(leads: list[Lead]) -> list[int]:
    """Індекси відкритих не забутих заявок (для точкових змін)."""
    return [i for i, l in enumerate(leads) if l.stage in OPEN_STAGES and not l.forgotten]


def generate(seed: int) -> dict[str, list[Lead]]:
    rng = random.Random(seed)
    reg = Registry(rng)

    olena = build_leads(rng, reg, OLENA)
    igor = build_leads(rng, reg, IGOR)
    maryna = build_leads(rng, reg, MARYNA)

    # Олена: «В одного договору сума порожня».
    rng.choice([l for l in olena if l.stage == CONTRACT]).amount_k = None

    # Ігор: один договір з порожньою сумою («так само») + кілька порожніх бюджетів.
    rng.choice([l for l in igor if l.stage == CONTRACT]).amount_k = None
    # «Один клієнт має той самий телефон, що й клієнт Олени: його ведуть обидва».
    # Це той самий клієнт і той самий виріб; суму Ігор оцінює сам (у межах виробу).
    o_shared = olena[rng.choice(open_active(olena))]
    i_idx = rng.choice(open_active(igor))
    reg.names.discard((igor[i_idx].first, igor[i_idx].last))
    reg.phones.discard(igor[i_idx].phone)
    igor[i_idx] = replace(igor[i_idx], first=o_shared.first, last=o_shared.last,
                          patronymic=o_shared.patronymic, phone=o_shared.phone,
                          product=o_shared.product,
                          amount_k=rng.randint(*PRICE_K[o_shared.product]))
    for i in rng.sample([i for i in open_active(igor) if i != i_idx], IGOR_EMPTY_BUDGETS):
        igor[i].amount_k = None

    # Марина: один договір з порожньою сумою, кілька порожніх стадій, 2–3 дублі рядків.
    rng.choice([l for l in maryna if l.stage == CONTRACT]).amount_k = None
    empty_stage = rng.sample(open_active(maryna), MARYNA_EMPTY_STAGES)
    for i in empty_stage:
        maryna[i].stage = None
    # Дублі: з непорожньою стадією, не забуті; один у звітному тижні, решта — до нього.
    dup_pool = [i for i in open_active(maryna) if i not in empty_stage]
    in_week = [i for i in dup_pool if maryna[i].created >= WEEK_START]
    before = [i for i in dup_pool if maryna[i].created < WEEK_START]
    dups = [rng.choice(in_week)] + rng.sample(before, MARYNA_DUPLICATES - 1)
    with_dups: list[Lead] = []
    for i, lead in enumerate(maryna):
        with_dups.append(lead)
        if i in dups:
            with_dups.append(replace(lead))  # точна копія рядка
    return {"olena": olena, "igor": igor, "maryna": with_dups}


# ------------------------------------------------------------ форматування

def step_text(l: Lead) -> str:
    return f"{l.step} {l.step_date:%d.%m}"


def format_rows(spec: ManagerSpec, leads: list[Lead]) -> list[list[str]]:
    rows = []
    for l in leads:
        stage = spec.stages[l.stage] if l.stage else ""
        source = spec.sources[l.source]
        if spec is OLENA:
            rows.append([f"{l.created:%d.%m.%Y}", f"{l.last} {l.first}", l.phone, source,
                         l.product, "" if l.amount_k is None else str(l.amount_k * 1000),
                         stage, step_text(l)])
        elif spec is IGOR:
            rows.append([f"{l.created.day} {IGOR_MONTHS[l.created.month]}", f"{l.first} {l.last}",
                         l.phone, source, l.product,
                         "" if l.amount_k is None else f"{l.amount_k} тис",
                         stage, step_text(l)])
        else:
            rows.append([l.created.isoformat(), f"{l.last} {l.first} {l.patronymic}", l.phone,
                         source, l.product,
                         "" if l.amount_k is None else f"{l.amount_k * 1000:.2f}",
                         stage, step_text(l)])
    return rows


def to_csv(columns: list[str], rows: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    w.writerows(rows)
    return buf.getvalue()


# ------------------------------------------------- перевірка специфікації

def parse_created(spec: ManagerSpec, s: str) -> date:
    if spec is OLENA:
        d, m, y = s.split(".")
        return date(int(y), int(m), int(d))
    if spec is IGOR:
        day, mon = s.split()
        month = {v: k for k, v in IGOR_MONTHS.items()}[mon]
        return date(2026, month, int(day))
    return date.fromisoformat(s)


def summarize(spec: ManagerSpec, csv_text: str) -> dict:
    """Рахує показники з уже відформатованого CSV (незалежно від генерації)."""
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    rows = list(reader)
    assert header == spec.columns, f"{spec.filename}: колонки не збігаються"
    unique = list(dict.fromkeys(tuple(r) for r in rows))
    to_canon = {v: k for k, v in spec.stages.items()}

    # Прострочений контакт: наступний крок передує даті звіту, а етап
    # не змінився. Історії етапів у таблиці немає, тому «не змінився» читаємо за
    # поточним станом: етап відкритий. overdue_other — прострочені кроки в рядках
    # із закритим або порожнім етапом; має бути 0, щоб визначення було однозначним.
    week = forgotten = overdue_other = empty_contract = empty_stage = empty_amount = 0
    for r in unique:
        created = parse_created(spec, r[0])
        stage = to_canon.get(r[6]) if r[6] else None
        assert r[6] == "" or stage, f"{spec.filename}: невідомий етап {r[6]!r}"
        m = re.search(r"(\d{2})\.(\d{2})$", r[7])
        assert m, f"{spec.filename}: у коментарі немає дати: {r[7]!r}"
        step_date = date(2026, int(m.group(2)), int(m.group(1)))
        assert created.year == 2026 and (created.month == 10 or created <= WEEK_END)
        assert r[3] in spec.sources.values() and r[4] in PRODUCTS
        assert r[2].startswith("+380 00 ")
        week += WEEK_START <= created <= WEEK_END
        forgotten += stage in OPEN_STAGES and step_date < REPORT_DATE
        overdue_other += stage not in OPEN_STAGES and step_date < REPORT_DATE
        empty_contract += stage == CONTRACT and r[5] == ""
        empty_stage += stage is None
        empty_amount += r[5] == ""
    return {
        "rows": len(rows), "unique": len(unique), "dups": len(rows) - len(unique),
        "week": week, "forgotten": forgotten, "overdue_other": overdue_other,
        "empty_contract": empty_contract, "empty_stage": empty_stage,
        "empty_amount": empty_amount,
        "phones": {r[2] for r in unique},
        "product_by_phone": {r[2]: r[4] for r in unique},
    }


def check(stats: dict[str, dict]) -> list[str]:
    o, i, m = stats["olena"], stats["igor"], stats["maryna"]
    shared = sorted(o["phones"] & i["phones"])
    rules = [
        ("Олена: 25 заявок", o["rows"] == 25 and o["dups"] == 0),
        ("Олена: 9 за тиждень", o["week"] == 9),
        ("Олена: 5 забутих", o["forgotten"] == 5),
        ("Олена: 1 договір з порожньою сумою", o["empty_contract"] == 1),
        ("Олена: інших порожніх сум немає", o["empty_amount"] == 1),
        ("Ігор: 25 заявок", i["rows"] == 25 and i["dups"] == 0),
        ("Ігор: 8 за тиждень", i["week"] == 8),
        ("Ігор: 4–6 забутих", 4 <= i["forgotten"] <= 6),
        ("Ігор: є порожні бюджети", i["empty_amount"] >= 1),
        ("Ігор: 1 договір з порожньою сумою", i["empty_contract"] == 1),
        ("Ігор: 1 спільний телефон з Оленою", len(shared) == 1),
        ("Спільний клієнт: той самий виріб в обох таблицях",
         all(o["product_by_phone"][p] == i["product_by_phone"][p] for p in shared)),
        ("Усі: прострочені кроки лише у відкритих етапах",
         o["overdue_other"] == i["overdue_other"] == m["overdue_other"] == 0),
        ("Марина: 25 унікальних заявок", m["unique"] == 25),
        ("Марина: 2–3 дублі рядків", 2 <= m["dups"] <= 3),
        ("Марина: 10 за тиждень (без дублів)", m["week"] == 10),
        ("Марина: 4–6 забутих", 4 <= m["forgotten"] <= 6),
        ("Марина: кілька порожніх стадій", m["empty_stage"] >= 2),
        ("Марина: 1 договір з порожньою сумою", m["empty_contract"] == 1),
        ("Марина: телефони не перетинаються з іншими",
         not (m["phones"] & (o["phones"] | i["phones"]))),
    ]
    return [f"{'OK  ' if ok else 'FAIL'} {name}" for name, ok in rules]


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Генератор штучних демо-таблиць заявок (промпти 1–3 вебінару).")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"seed (за замовчуванням {DEFAULT_SEED})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="папка для CSV (за замовчуванням data/)")
    ap.add_argument("--force", action="store_true", help="перезаписати наявні файли")
    ap.add_argument("--dry-run", action="store_true", help="лише перевірити, нічого не записувати")
    args = ap.parse_args(argv)

    leads = generate(args.seed)
    specs = {"olena": OLENA, "igor": IGOR, "maryna": MARYNA}
    texts = {k: to_csv(s.columns, format_rows(s, leads[k])) for k, s in specs.items()}
    stats = {k: summarize(specs[k], t) for k, t in texts.items()}

    print(f"ШТУЧНІ ДЕМО-ДАНІ · seed {args.seed}")
    print(f"{'файл':<22}{'рядків':>7}{'унік.':>7}{'дублі':>7}{'тиждень':>9}{'забуті':>8}"
          f"{'порожн. сум':>13}{'порожн. етап':>14}")
    for k, s in stats.items():
        print(f"{specs[k].filename:<22}{s['rows']:>7}{s['unique']:>7}{s['dups']:>7}{s['week']:>9}"
              f"{s['forgotten']:>8}{s['empty_amount']:>13}{s['empty_stage']:>14}")
    results = check(stats)
    print("\n".join(results))
    if any(r.startswith("FAIL") for r in results):
        print("Специфікацію не виконано — файли не записано.", file=sys.stderr)
        return 1
    if args.dry_run:
        print("--dry-run: файли не записано.")
        return 0

    targets = {k: args.out / specs[k].filename for k in specs}
    existing = [p for p in targets.values() if p.exists()]
    if existing and not args.force:
        print("Файли вже існують, не перезаписую (додайте --force):", file=sys.stderr)
        for p in existing:
            print(f"  {p}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    for k, p in targets.items():
        p.write_text(texts[k], encoding="utf-8", newline="")
        print(f"записано: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
