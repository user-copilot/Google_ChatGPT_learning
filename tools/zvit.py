#!/usr/bin/env python3
"""Тижневий звіт по заявках меблевої студії.

Читає три таблиці менеджерів із data/, приводить колонки, дати, суми, стадії
й канали до одного вигляду і формує п'ять результатів (brief.md):
  reports/zvedena.csv    — зведена таблиця: усі рядки, включно з дублями, з позначками;
  reports/zvit.md        — звіт на один екран (промпт 9 вебінару);
  history/zvit-<дата>.md — копія звіту; архів ніколи не перезаписується (-2, -3, ...);
  reports/managers.md    — внутрішні висновки щодо кожного менеджера;
  reports/chernetky.md   — чернетки повідомлень клієнтам (промпт 11), нічого не надсилається.

Ключові правила (brief.md, розділ «Уточнення»):
  - вихідні CSV лише читаються;
  - дубль заявки — точна копія рядка: значення всіх полів збігаються повністю
    (без обрізання пробілів і зміни регістру);
  - клієнт — за телефоном; різні заявки одного клієнта в різних менеджерів рахуються обидві;
  - порожні й некоректні значення не замінюються нулями — вони «невідомо»;
  - забута заявка: дата наступного кроку < дати звіту, стадія непорожня і відкрита;
  - «Крок на сьогодні»: дата кроку = дата звіту; не забута, без чернетки;
  - «Кому написати сьогодні»: до 10 забутих клієнтів, спершу найдовше прострочені,
    за рівності — раніша дата створення; клієнт із простроченими заявками в кількох
    менеджерів — одна позиція, без автоматичної чернетки, «потребує ручного рішення».

Тільки стандартна бібліотека Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP_CONTACTS = 10  # «до 10 клієнтів» (промпт 9)


class DataError(Exception):
    """Помилка структури вхідних даних, з якою звіт будувати не можна."""


# --------------------------------------------------------------- налаштування

@dataclass(frozen=True)
class Source:
    manager: str
    filename: str
    columns: dict  # поле -> назва колонки в таблиці менеджера


SOURCES = (
    Source("Олена", "zayavky_olena.csv", {
        "created": "Дата", "client": "Клієнт", "phone": "Телефон", "channel": "Джерело",
        "product": "Що замовляє", "amount": "Сума", "stage": "Етап", "note": "Коментар"}),
    Source("Ігор", "zayavky_igor.csv", {
        "created": "Коли", "client": "Ім'я", "phone": "Тел.", "channel": "Звідки прийшов",
        "product": "Виріб", "amount": "Бюджет", "stage": "Статус", "note": "Нотатки"}),
    Source("Марина", "zayavky_maryna.csv", {
        "created": "дата_створення", "client": "клієнт_піб", "phone": "телефон",
        "channel": "канал_залучення", "product": "товар", "amount": "сума_грн",
        "stage": "стадія_угоди", "note": "примітка"}),
)
MANAGER_ORDER = [s.manager for s in SOURCES]

OPEN_STAGES = ("Нова", "Прорахунок", "Замір")
CLOSED_STAGES = ("Договір", "Відмова")
STAGES = OPEN_STAGES + CLOSED_STAGES
STAGE_MAP = {
    "нова": "Нова", "новий": "Нова",
    "прорахунок": "Прорахунок", "рахую": "Прорахунок", "розрахунок": "Прорахунок",
    "замір": "Замір", "заміряли": "Замір",
    "договір": "Договір", "підписали": "Договір", "угода": "Договір",
    "відмова": "Відмова", "злився": "Відмова", "втрачено": "Відмова",
}
CHANNEL_MAP = {
    "instagram": "Instagram", "інста": "Instagram",
    "telegram": "Telegram", "тг": "Telegram",
    "рекомендація": "Рекомендація", "по рекомендації": "Рекомендація",
    "google карти": "Google Карти", "карти": "Google Карти",
    "дзвінок": "Дзвінок", "дзвонив": "Дзвінок",
    "facebook": "Facebook", "google ads": "Google Ads",
}
UA_MONTHS = {  # скорочення місяців (за префіксом)
    "січ": 1, "лют": 2, "бер": 3, "квіт": 4, "трав": 5, "черв": 6,
    "лип": 7, "серп": 8, "вер": 9, "жовт": 10, "лист": 11, "груд": 12,
}
UNKNOWN = "невідомо"


# ----------------------------------------------------------------- розбір
# Розбір значень працює з обрізаними копіями; самі значення рядка не змінюються.

def ua_month(token: str) -> int | None:
    t = token.lower().rstrip(".")
    for prefix in sorted(UA_MONTHS, key=len, reverse=True):
        if t.startswith(prefix):
            return UA_MONTHS[prefix]
    return None


def parse_created(raw: str, ref: date) -> tuple[date | None, str | None]:
    """Дата заявки: 26.10.2026, 2026-10-28, «27 жовт» (рік не вказано — рік дати звіту)."""
    s = raw.strip()
    if not s:
        return None, "порожня дата заявки"
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
            return date(int(m[1]), int(m[2]), int(m[3])), None
        if m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s):
            return date(int(m[3]), int(m[2]), int(m[1])), None
        if m := re.fullmatch(r"(\d{1,2})\s+([^\W\d_]+)\.?(?:\s+(\d{4}))?", s):
            month = ua_month(m[2])
            if month:
                if m[3]:
                    return date(int(m[3]), month, int(m[1])), None
                d = date(ref.year, month, int(m[1]))
                if d > ref:  # рік не вказано: заявка не може бути пізніше дати звіту
                    d = date(ref.year - 1, month, int(m[1]))
                return d, None
    except ValueError:
        return None, f"некоректна дата заявки «{s}»"
    return None, f"нерозпізнаний формат дати заявки «{s}»"


def parse_amount(raw: str) -> tuple[Decimal | None, str | None]:
    """Сума: 85000, 85000.00, «85 тис». Порожньо -> None (не нуль)."""
    s = raw.strip()
    if not s:
        return None, None
    t = s.lower().replace(" ", " ").replace("грн", "").strip()
    mult = Decimal(1)
    if m := re.fullmatch(r"(.+?)\s*тис\.?", t):
        t, mult = m[1], Decimal(1000)
    t = t.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None, f"некоректна сума «{s}»"
    return Decimal(t) * mult, None


def parse_stage(raw: str) -> tuple[str | None, str | None]:
    s = raw.strip()
    if not s:
        return None, None
    stage = STAGE_MAP.get(s.lower())
    return (stage, None) if stage else (None, f"невідома стадія «{s}»")


def parse_channel(raw: str) -> tuple[str | None, str | None]:
    s = raw.strip()
    if not s:
        return None, None
    ch = CHANNEL_MAP.get(s.lower())
    return (ch, None) if ch else (s, f"невідомий канал «{s}» (залишено як є)")


STEP_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\d)")


def parse_step(raw: str, created: date | None, ref: date) -> tuple[str, date | None, str | None]:
    """Наступний крок і його дата з коментаря «передзвонити 28.10».

    Рік не вказано: береться рік заявки (або звіту); якщо так виходить більш
    ніж на пів року раніше за заявку — це наступний рік (грудень -> січень).
    """
    s = raw.strip()
    if not s:
        return "", None, "немає наступного кроку"
    found = STEP_DATE_RE.findall(s)
    text = STEP_DATE_RE.sub("", s).strip(" ,;:-")
    if not found:
        return text, None, "у коментарі немає дати кроку"
    if len(found) > 1:
        return text, None, "у коментарі кілька дат — дата кроку неоднозначна"
    d, m, y = found[0]
    try:
        if y:
            step = date(int(y), int(m), int(d))
        else:
            base = created or ref
            step = date(base.year, int(m), int(d))
            if created and (created - step).days > 183:
                step = date(base.year + 1, int(m), int(d))
    except ValueError:
        return text, None, f"некоректна дата кроку «{d}.{m}»"
    if created and step < created:
        return text, step, "дата кроку раніша за дату заявки"
    return text, step, None


def phone_key(raw: str) -> str | None:
    """Ключ клієнта: останні 9 цифр номера (+380 00 123 45 67 == 0001234567)."""
    digits = re.sub(r"\D", "", raw)
    return digits[-9:] if len(digits) >= 9 else None


# ------------------------------------------------------------------ дані

@dataclass
class Lead:
    manager: str
    source_file: str
    row_no: int               # номер рядка у CSV (заголовок — рядок 1)
    raw: dict                 # поле -> значення точно як у таблиці
    created: date | None
    client: str
    phone: str
    phone_key: str | None
    channel: str | None
    product: str
    amount: Decimal | None
    stage: str | None         # єдиний етап; None — порожньо або невідома стадія
    step_text: str
    step_date: date | None
    issues: list = field(default_factory=list)
    dup_of: int | None = None  # рядок-оригінал, якщо це точна копія
    in_week: bool = False
    forgotten: bool = False
    overdue_days: int | None = None
    due_today: bool = False
    shared_with: list = field(default_factory=list)
    contact_rank: int | None = None  # позиція клієнта в загальному списку забутих
    manual: bool = False             # клієнт прострочений у кількох менеджерів

    @property
    def is_duplicate(self) -> bool:
        return self.dup_of is not None

    @property
    def stage_blank(self) -> bool:
        return not self.raw["stage"].strip()

    @property
    def in_contact_list(self) -> bool:
        return self.contact_rank is not None and self.contact_rank <= TOP_CONTACTS


@dataclass
class Contact:
    """Забутий клієнт у загальній аналітиці (один телефон — один клієнт)."""
    rank: int
    leads: list  # прострочені заявки клієнта (у різних менеджерів)

    @property
    def managers(self) -> list[str]:
        return [m for m in MANAGER_ORDER if any(l.manager == m for l in self.leads)]

    @property
    def manual(self) -> bool:
        return len(self.managers) > 1

    @property
    def overdue_days(self) -> int:
        return max(l.overdue_days for l in self.leads)

    @property
    def created(self) -> date:
        return min((l.created for l in self.leads if l.created), default=date.max)

    @property
    def main(self) -> Lead:
        return self.leads[0]


@dataclass
class Period:
    report_date: date
    week_start: date
    week_end: date
    origin: str  # звідки взято дату


def load_source(text: str, src: Source, ref: date) -> tuple[list[Lead], int]:
    """Розбирає CSV одного менеджера. Повертає заявки і кількість порожніх рядків."""
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None:
        raise DataError(f"{src.filename}: файл порожній")
    header = [h.strip().lstrip("﻿") for h in header]
    missing = [c for c in src.columns.values() if c not in header]
    if missing:
        raise DataError(f"{src.filename}: немає колонок {missing}; є {header}")
    idx = {f: header.index(c) for f, c in src.columns.items()}

    leads, seen, blank = [], {}, 0
    for row_no, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            blank += 1
            continue
        # Точна копія: значення всіх полів після читання CSV збігаються повністю.
        dup_of = seen.setdefault(tuple(row), row_no)
        issues = []
        if len(row) != len(header):
            issues.append(f"кількість колонок {len(row)} замість {len(header)}")
            row = (row + [""] * len(header))[:len(header)]
        raw = {f: row[i] for f, i in idx.items()}

        created, e = parse_created(raw["created"], ref)
        issues += [e] if e else []
        amount, e = parse_amount(raw["amount"])
        issues += [e] if e else []
        stage, e = parse_stage(raw["stage"])
        issues += [e] if e else []
        channel, e = parse_channel(raw["channel"])
        issues += [e] if e else []
        step_text, step_date, e = parse_step(raw["note"], created, ref)
        issues += [e] if e else []
        pk = phone_key(raw["phone"])
        if pk is None:
            issues.append("порожній або некоректний телефон")
        if not raw["client"].strip():
            issues.append("порожнє ім'я клієнта")

        leads.append(Lead(
            manager=src.manager, source_file=src.filename, row_no=row_no, raw=raw,
            created=created, client=raw["client"].strip(), phone=raw["phone"].strip(),
            phone_key=pk, channel=channel, product=raw["product"].strip(), amount=amount,
            stage=stage, step_text=step_text, step_date=step_date, issues=issues,
            dup_of=None if dup_of == row_no else dup_of,
        ))
    return leads, blank


# --------------------------------------------------------------- розрахунок

def read_period(brief_text: str | None, today: date) -> Period:
    """Дата звіту і тиждень з brief.md; якщо їх немає — сьогодні і попередній тиждень."""
    if brief_text:
        m = re.search(r"Дата звіту:\s*\**\s*(\d{2})\.(\d{2})\.(\d{4})", brief_text)
        w = re.search(r"Звітний тиждень:\s*\**\s*(\d{2})\.(\d{2})\.(\d{4})\s*[–—-]\s*"
                      r"(\d{2})\.(\d{2})\.(\d{4})", brief_text)
        if m:
            rd = date(int(m[3]), int(m[2]), int(m[1]))
            if w:
                ws = date(int(w[3]), int(w[2]), int(w[1]))
                we = date(int(w[6]), int(w[5]), int(w[4]))
            else:
                we = rd - timedelta(days=rd.weekday() + 1)
                ws = we - timedelta(days=6)
            return Period(rd, ws, we, "brief.md")
    we = today - timedelta(days=today.weekday() + 1)
    return Period(today, we - timedelta(days=6), we, "сьогоднішня дата")


def analyze(leads: list[Lead], p: Period) -> list[Lead]:
    """Позначає тиждень, забутих, крок на сьогодні, спільних клієнтів. Повертає унікальні."""
    unique = [l for l in leads if not l.is_duplicate]
    for l in unique:
        l.in_week = l.created is not None and p.week_start <= l.created <= p.week_end
        if l.stage in OPEN_STAGES and l.step_date is not None:  # None — порожня/невідома
            l.forgotten = l.step_date < p.report_date
            l.due_today = l.step_date == p.report_date
            if l.forgotten:
                l.overdue_days = (p.report_date - l.step_date).days
    by_phone: dict[str, set] = {}
    for l in unique:
        if l.phone_key:
            by_phone.setdefault(l.phone_key, set()).add(l.manager)
    for l in unique:
        managers = by_phone.get(l.phone_key, set())
        if len(managers) > 1:
            l.shared_with = [m for m in MANAGER_ORDER if m in managers and m != l.manager]
    return unique


def contact_groups(unique: list[Lead]) -> list[Contact]:
    """Усі забуті клієнти в загальній аналітиці, впорядковані для «Кому написати сьогодні».

    Один телефон — один клієнт. Порядок: найбільше прострочення серед заявок клієнта,
    за рівності — найраніша дата створення, далі менеджер і рядок (лише для стабільності).
    Позначає заявки рангом клієнта і ознакою ручного рішення.
    """
    groups: dict = {}
    for l in unique:
        if l.forgotten:
            key = l.phone_key or ("без телефону", l.manager, l.row_no)
            groups.setdefault(key, []).append(l)
    contacts = [Contact(0, sorted(ls, key=lambda l: (MANAGER_ORDER.index(l.manager), l.row_no)))
                for ls in groups.values()]
    contacts.sort(key=lambda c: (-c.overdue_days, c.created,
                                 MANAGER_ORDER.index(c.main.manager), c.main.row_no))
    for rank, c in enumerate(contacts, 1):
        c.rank = rank
        for l in c.leads:
            l.contact_rank, l.manual = rank, c.manual
    return contacts


def propagate_to_duplicates(leads: list[Lead]) -> None:
    """Точні копії переймають позначки оригіналу (для зведеної таблиці), але не рахуються."""
    orig = {(l.manager, l.row_no): l for l in leads if not l.is_duplicate}
    for l in leads:
        if l.is_duplicate:
            o = orig[(l.manager, l.dup_of)]
            for attr in ("in_week", "forgotten", "overdue_days", "due_today", "shared_with",
                         "contact_rank", "manual"):
                setattr(l, attr, getattr(o, attr))


def same_phone_within_manager(unique: list[Lead]) -> list[tuple[Lead, Lead]]:
    """Різні (не точні копії) рядки одного менеджера з тим самим телефоном."""
    pairs, first = [], {}
    for l in unique:
        if not l.phone_key:
            continue
        k = (l.manager, l.phone_key)
        if k in first:
            pairs.append((first[k], l))
        else:
            first[k] = l
    return pairs


def manager_stats(m: str, leads: list[Lead], unique: list[Lead]) -> dict:
    """Індивідуальна аналітика: кожна заявка рахується у свого менеджера."""
    rows = [l for l in leads if l.manager == m]
    u = [l for l in unique if l.manager == m]
    contracts = [l for l in u if l.stage == "Договір"]
    return {
        "rows": len(rows),
        "dups": [l for l in rows if l.is_duplicate],
        "unique": u,
        "week": [l for l in u if l.in_week],
        "stages": Counter(l.stage or UNKNOWN for l in u),
        "contracts": contracts,
        "contracts_week": [l for l in contracts if l.in_week],
        "contracts_no_amount": [l for l in contracts if l.amount is None],
        "amount_known": sum(l.amount is not None for l in u),
        "amount_missing": [l for l in u if l.amount is None],
        "contracts_sum": sum((l.amount for l in contracts if l.amount is not None), Decimal(0)),
        "open_sum": sum((l.amount for l in u if l.stage in OPEN_STAGES and l.amount is not None),
                        Decimal(0)),
        "forgotten": sorted([l for l in u if l.forgotten], key=lambda l: l.contact_rank),
        "due_today": [l for l in u if l.due_today],
        "empty_stage": [l for l in u if l.stage_blank],
        "issues": [l for l in u if l.issues],
        "shared": [l for l in u if l.shared_with],
        "week_channels": Counter(l.channel or UNKNOWN for l in u if l.in_week),
    }


# ---------------------------------------------------------- форматування

def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def money(x: Decimal | None) -> str:
    if x is None:
        return UNKNOWN
    q = x.quantize(Decimal("0.01"))
    s = f"{int(q):,}".replace(",", " ")
    if q != int(q):
        s += f",{str(q).split('.')[1]}"
    return f"{s} грн"


def d(x: date | None, year: bool = True) -> str:
    if x is None:
        return UNKNOWN
    return f"{x:%d.%m.%Y}" if year else f"{x:%d.%m}"


def days(n: int) -> str:
    return f"{n} {plural(n, 'день', 'дні', 'днів')}"


def reason(l: Lead) -> str:
    return (f"крок «{l.step_text or UNKNOWN}» на {d(l.step_date, False)} прострочено на "
            f"{days(l.overdue_days)}, стадія «{l.stage}»")


def md_table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def names(ls: list[Lead]) -> str:
    return ", ".join(f"{l.client} (рядок {l.row_no})" for l in ls) or "немає"


def list_status(l: Lead) -> str:
    if not l.in_contact_list:
        return f"ні — поза лімітом {TOP_CONTACTS} (позиція {l.contact_rank})"
    if l.manual:
        return f"так, №{l.contact_rank} — ⚠ потребує ручного рішення (кілька менеджерів)"
    return f"так, №{l.contact_rank}"


# ---------------------------------------------------------------- звіти

def channel_rows(unique: list[Lead]) -> list[list]:
    chans = {l.channel or UNKNOWN for l in unique}
    rows = []
    for c in chans:
        ls = [l for l in unique if (l.channel or UNKNOWN) == c]
        rows.append([c, sum(l.in_week for l in ls), len(ls),
                     sum(l.stage == "Договір" for l in ls),
                     sum(l.stage == "Договір" and l.in_week for l in ls)])
    return sorted(rows, key=lambda r: (-r[1], -r[2], r[0]))


def contact_line(i: int, c: Contact) -> str:
    if c.manual:
        parts = "; ".join(f"{l.manager}: {reason(l)}" for l in c.leads)
        return (f"{i}. **{c.main.client}** ({c.main.phone}) — ⚠ **потребує ручного рішення**: "
                f"прострочено в кількох менеджерів ({parts}). Погодьте відповідального; чернетку не створено.")
    l = c.main
    extra = f" Клієнта веде також: {', '.join(l.shared_with)}." if l.shared_with else ""
    return f"{i}. **{l.client}** ({l.manager}, {l.phone}) — {reason(l)}.{extra}"


def render_zvit(ctx: dict) -> str:
    p, unique, stats = ctx["period"], ctx["unique"], ctx["stats"]
    contacts, all_contacts = ctx["contacts"], ctx["all_contacts"]
    week = [l for l in unique if l.in_week]
    ch = channel_rows(unique)
    top_n = max((r[1] for r in ch), default=0)
    top_ch = [r[0] for r in ch if r[1] == top_n and top_n > 0]
    contracts = [l for l in unique if l.stage == "Договір"]
    dups = [l for l in ctx["leads"] if l.is_duplicate]
    shared = ctx["shared_groups"]
    empty_stage = [l for l in unique if l.stage_blank]
    clients = len({l.phone_key for l in unique if l.phone_key})

    per = lambda key: ", ".join(f"{m} — {len(stats[m][key])}" for m in MANAGER_ORDER)
    summary = [
        f"За тиждень {d(p.week_start)}–{d(p.week_end)} надійшло {len(week)} "
        f"{plural(len(week), 'нова заявка', 'нові заявки', 'нових заявок')} ({per('week')}).",
        (f"Найбільше заявок тижня дав канал {', '.join(top_ch)} — {top_n}." if top_ch
         else "Заявок тижня з відомим каналом немає."),
        f"Договорів серед заявок тижня — {sum(l.in_week for l in contracts)}; усього в таблицях "
        f"{len(contracts)} {plural(len(contracts), 'договір', 'договори', 'договорів')}, з них без суми — "
        f"{sum(l.amount is None for l in contracts)}.",
        f"Забутих клієнтів — {len(all_contacts)} (прострочених заявок: {per('forgotten')})"
        + (f"; найдовше чекає {all_contacts[0].main.client} ({', '.join(all_contacts[0].managers)}, "
           f"{days(all_contacts[0].overdue_days)})." if all_contacts else "."),
        f"Дані потребують уваги: {len(dups)} {plural(len(dups), 'точна копія', 'точні копії', 'точних копій')} "
        f"рядків, {len(empty_stage)} {plural(len(empty_stage), 'порожня стадія', 'порожні стадії', 'порожніх стадій')}, "
        f"{len(shared)} {plural(len(shared), 'клієнт', 'клієнти', 'клієнтів')} у кількох менеджерів.",
    ]
    mgr_rows = [[m, len(stats[m]["week"]), len(stats[m]["unique"]), len(stats[m]["contracts_week"]),
                 len(stats[m]["contracts"]), len(stats[m]["forgotten"]), len(stats[m]["due_today"]),
                 money(stats[m]["contracts_sum"]), len(stats[m]["contracts_no_amount"])]
                for m in MANAGER_ORDER]

    out = [f"# Тижневий звіт · {d(p.report_date)}", ""]
    if ctx["demo"]:
        out += ["> ⚠️ Штучні демонстраційні дані (див. brief.md), не реальні дані студії.", ""]
    out += ["## Резюме", " ".join(summary), "",
            f"Заявок: {len(unique)} (без точних копій) від {clients} "
            f"{plural(clients, 'клієнта', 'клієнтів', 'клієнтів')} (за телефоном).", "",
            "## Канали",
            md_table(["Канал", "Заявок тижня", "Усього заявок", "Договорів усього",
                      "Договорів серед заявок тижня"], ch), ""]
    no_contract = [r[0] for r in ch if r[3] == 0]
    out += [f"Канали без жодного договору: {', '.join(no_contract) or 'немає'}.", "",
            "## Менеджери",
            md_table(["Менеджер", "Заявок тижня", "Усього заявок", "Договорів серед заявок тижня",
                      "Договорів усього", "Забутих заявок", "Крок на сьогодні",
                      "Сума договорів (відома)", "Договорів без суми"], mgr_rows), "",
            f"## Кому написати сьогодні (до {TOP_CONTACTS})"]
    out += [contact_line(i, c) for i, c in enumerate(contacts, 1)] or ["Забутих клієнтів немає."]
    rest = len(all_contacts) - len(contacts)
    if rest > 0:
        out.append(f"\nЩе {rest} {plural(rest, 'забутий клієнт', 'забуті клієнти', 'забутих клієнтів')} "
                   f"поза лімітом — у `reports/managers.md` і `reports/zvedena.csv`.")
    out += ["", "## Дублі", "**Клієнти в кількох менеджерів** (заявки рахуються в кожного):"]
    out += [f"- {ls[0].client} ({ls[0].phone}) — ведуть {' і '.join(l.manager for l in ls)}: "
            f"домовтеся, хто веде." for ls in shared.values()] or ["- немає."]
    out.append("\n**Точні копії рядків** (не рахуються):")
    out += [f"- {l.manager}: рядок {l.row_no} повторює рядок {l.dup_of} ({l.client})." for l in dups] \
        or ["- немає."]
    if ctx["same_phone"]:
        out.append("\n**Той самий телефон у різних рядках одного менеджера** (рахуються, перевірте):")
        out += [f"- {a.manager}: рядки {a.row_no} і {b.row_no} ({a.phone})." for a, b in ctx["same_phone"]]
    out += ["", f"_Дата звіту взята з: {p.origin}. Дати підписання договорів у таблицях немає, тому "
                f"«договори серед заявок тижня» — не «укладені за тиждень»._", ""]
    return "\n".join(out)


def render_managers(ctx: dict) -> str:
    p, stats = ctx["period"], ctx["stats"]
    out = [f"# Висновки щодо менеджерів · {d(p.report_date)}", "",
           "_Внутрішній документ. Усі цифри пораховані скриптом `tools/zvit.py` з таблиць у `data/`. "
           "Індивідуальна аналітика: кожна заявка рахується у свого менеджера; точні копії рядків не рахуються._",
           ""]
    if ctx["demo"]:
        out += ["> ⚠️ Штучні демонстраційні дані (див. brief.md), не реальні дані студії.", ""]
    rows = [
        ["Рядків у таблиці"] + [stats[m]["rows"] for m in MANAGER_ORDER],
        ["Точних копій рядків"] + [len(stats[m]["dups"]) for m in MANAGER_ORDER],
        ["Унікальних заявок"] + [len(stats[m]["unique"]) for m in MANAGER_ORDER],
        [f"Заявок тижня {d(p.week_start, False)}–{d(p.week_end, False)}"]
        + [len(stats[m]["week"]) for m in MANAGER_ORDER],
    ]
    rows += [[f"Стадія «{s}»"] + [stats[m]["stages"].get(s, 0) for m in MANAGER_ORDER]
             for s in STAGES + (UNKNOWN,)]
    rows += [
        ["Договорів серед заявок тижня"] + [len(stats[m]["contracts_week"]) for m in MANAGER_ORDER],
        ["Сума договорів (відома)"] + [money(stats[m]["contracts_sum"]) for m in MANAGER_ORDER],
        ["Договорів без суми"] + [len(stats[m]["contracts_no_amount"]) for m in MANAGER_ORDER],
        ["Заявок із відомою сумою"] + [f"{stats[m]['amount_known']} з {len(stats[m]['unique'])}"
                                        for m in MANAGER_ORDER],
        ["Сума відкритих заявок (відома)"] + [money(stats[m]["open_sum"]) for m in MANAGER_ORDER],
        ["Забутих заявок"] + [len(stats[m]["forgotten"]) for m in MANAGER_ORDER],
        ["З них у списку «Кому написати сьогодні»"]
        + [sum(l.in_contact_list for l in stats[m]["forgotten"]) for m in MANAGER_ORDER],
        ["Крок на сьогодні"] + [len(stats[m]["due_today"]) for m in MANAGER_ORDER],
    ]
    out += ["## Порівняння", md_table(["Показник"] + MANAGER_ORDER, rows), ""]

    for m in MANAGER_ORDER:
        s = stats[m]
        src = next(x for x in SOURCES if x.manager == m)
        out += [f"## {m}", f"Файл: `data/{src.filename}`.", ""]
        wc = s["week_channels"]
        out.append(f"- **Заявки тижня:** {len(s['week'])}"
                   + (f" — {', '.join(f'{c} {n}' for c, n in sorted(wc.items(), key=lambda x: (-x[1], x[0])))}."
                      if wc else "."))
        out.append(f"- **Договори:** {len(s['contracts'])} усього, серед заявок тижня — "
                   f"{len(s['contracts_week'])}; відома сума договорів — {money(s['contracts_sum'])}.")
        if s["contracts_no_amount"]:
            out.append(f"- **Договори без суми:** {names(s['contracts_no_amount'])} — сума: {UNKNOWN}, "
                       f"у підсумки не входить.")
        out.append(f"- **Суми:** відомі для {s['amount_known']} з {len(s['unique'])} заявок"
                   + (f"; {UNKNOWN} — {names(s['amount_missing'])}." if s["amount_missing"] else "."))
        refusals = s["stages"].get("Відмова", 0)
        if refusals:
            out.append(f"- **Відмови:** {refusals}. Причини відмов у таблиці не вказані — {UNKNOWN}.")
        out.append(f"- **Порожня стадія (статус {UNKNOWN}):** {names(s['empty_stage'])}.")
        out += ["", f"**Забуті заявки ({len(s['forgotten'])}):**"]
        if s["forgotten"]:
            out.append(md_table(
                ["Рядок", "Клієнт", "Телефон", "Стадія", "Крок", "Дата кроку", "Прострочено",
                 "У списку «Кому написати сьогодні»"],
                [[l.row_no, l.client, l.phone, l.stage, l.step_text, d(l.step_date),
                  days(l.overdue_days), list_status(l)] for l in s["forgotten"]]))
        else:
            out.append("немає.")
        out += ["", f"**Крок на сьогодні ({d(p.report_date)}), не прострочено ({len(s['due_today'])}):** "
                + ("; ".join(f"{l.client} (рядок {l.row_no}) — «{l.step_text}», стадія «{l.stage}»"
                             for l in s["due_today"]) or "немає") + "."]
        if s["shared"]:
            out += ["", "**Спільні клієнти:** " + "; ".join(
                f"{l.client} ({l.phone}) веде також {', '.join(l.shared_with)}" for l in s["shared"]) + "."]
        out += ["", "**Проблеми даних:** " + ("; ".join(
            f"рядок {l.row_no}: {', '.join(l.issues)}" for l in s["issues"]) + "." if s["issues"]
            else "некоректних дат, сум, стадій чи каналів не виявлено.")]

        recs = []
        if s["forgotten"]:
            n = len(s["forgotten"])
            recs.append(f"Зв'язатися з {n} {plural(n, 'клієнтом', 'клієнтами', 'клієнтами')} із простроченим "
                        f"кроком (таблиця вище), спершу — {s['forgotten'][0].client}.")
        for l in s["forgotten"]:
            if l.manual:
                recs.append(f"Погодити, хто відповідає за клієнта {l.client}: заявки прострочені також у "
                            f"менеджерів ({', '.join(l.shared_with)}); чернетку не створено.")
        if s["due_today"]:
            recs.append(f"Виконати кроки, заплановані на {d(p.report_date, False)}: {names(s['due_today'])}.")
        if s["contracts_no_amount"]:
            recs.append(f"Внести суму договору: {names(s['contracts_no_amount'])}.")
        other_missing = [l for l in s["amount_missing"] if l.stage != "Договір"]
        if other_missing:
            recs.append(f"За можливості внести суму/бюджет: {names(other_missing)}.")
        if s["empty_stage"]:
            recs.append(f"Вказати стадію: {names(s['empty_stage'])}.")
        if s["dups"]:
            recs.append("Прибрати точні копії рядків: " + ", ".join(
                f"рядок {l.row_no} = рядок {l.dup_of}" for l in s["dups"]) + ".")
        for l in s["shared"]:
            recs.append(f"Погодити, хто веде клієнта {l.client} (його веде також: {', '.join(l.shared_with)}).")
        if refusals:
            recs.append("Записувати причину відмови — зараз її немає в таблиці.")
        if s["issues"]:
            recs.append("Виправити записи з проблемами даних (вище).")
        out += ["", "**Чернетка рекомендацій менеджеру:**"]
        out += [f"{i}. {r}" for i, r in enumerate(recs, 1)] or ["Зауважень немає."]
        out.append("")
    return "\n".join(out)


# Нагадування і одне питання для типових кроків. Нічого не обіцяємо понад таблицю.
STEP_PHRASES = {
    "передзвонити": ("ми планували вам передзвонити", "Коли вам зручно поговорити?"),
    "уточнити розміри": ("ми планували уточнити розміри", "Коли вам зручно уточнити розміри?"),
    "надіслати прорахунок": ("ми планували надіслати вам прорахунок", "Чи ще актуальний для вас прорахунок?"),
    "обговорити прорахунок": ("ми планували обговорити прорахунок", "Коли вам зручно обговорити прорахунок?"),
    "виїхати на замір": ("ми планували замір", "Коли вам зручно домовитися про замір?"),
    "погодити проєкт після заміру": ("ми планували погодити проєкт після заміру",
                                     "Коли вам зручно погодити проєкт?"),
}


def draft_text(l: Lead) -> str:
    phrase = STEP_PHRASES.get(l.step_text.lower())
    if phrase:
        reminder = f"За нашими записами, {d(l.step_date, False)} {phrase[0]}."
        question = phrase[1]
    else:
        reminder = (f"За нашими записами, на {d(l.step_date, False)} був запланований "
                    f"наступний крок: «{l.step_text}».")
        question = "Коли вам зручно зв'язатися?"
    product = f" (виріб: {l.product})" if l.product else ""
    return (f"Добрий день! Це {l.manager}, студія меблів на замовлення. "
            f"Пишу щодо вашої заявки{product}. {reminder} {question}")


def render_chernetky(ctx: dict) -> str:
    p, contacts = ctx["period"], ctx["contacts"]
    n_drafts = sum(not c.manual for c in contacts)
    out = [f"# Чернетки повідомлень клієнтам · {d(p.report_date)}", "",
           "> ⚠️ **Лише чернетки. Нічого не надіслано.** Перед надсиланням у Telegram чи Viber менеджер "
           "перевіряє текст і дані клієнта.", ""]
    if ctx["demo"]:
        out += ["> ⚠️ Штучні демонстраційні дані: клієнти й телефони вигадані.", ""]
    out += [f"Клієнти зі списку «Кому написати сьогодні» ({len(contacts)}), спершу ті, про кого забули "
            f"найдовше. Чернеток: {n_drafts}. Кожна чернетка: привітання, нагадування про наступний крок "
            f"з таблиці і одне питання.", ""]
    for i, c in enumerate(contacts, 1):
        if c.manual:
            out += [f"## {i}. {c.main.client} — ⚠ потребує ручного рішення",
                    f"Телефон: {c.main.phone} · прострочено в менеджерів: " + "; ".join(
                        f"{l.manager} (рядок {l.row_no}, «{l.step_text}» {d(l.step_date)}, "
                        f"стадія {l.stage})" for l in c.leads),
                    "", "Чернетку **не створено**: спершу менеджери погоджують, хто відповідає за клієнта.", ""]
            continue
        l = c.main
        out += [f"## {i}. {l.client} — менеджер {l.manager}",
                f"Телефон: {l.phone} · канал: {l.channel or UNKNOWN} · стадія: {l.stage} · "
                f"крок у таблиці: «{l.step_text}» {d(l.step_date)} · прострочено на {days(l.overdue_days)}"
                + (f" · клієнта веде також: {', '.join(l.shared_with)}" if l.shared_with else ""),
                "", f"> {draft_text(l)}", ""]
    if not contacts:
        out.append("Забутих клієнтів немає — чернетки не потрібні.")
    return "\n".join(out)


ZVEDENA_COLUMNS = [
    "manager", "source_file", "row_no", "created", "client", "phone", "channel", "product",
    "amount", "stage", "stage_raw", "next_step", "next_step_date", "in_week", "is_duplicate",
    "duplicate_of_row", "forgotten", "overdue_days", "in_contact_list", "contact_rank",
    "manual_decision", "due_today", "shared_with", "issues",
]


def render_zvedena(leads: list[Lead]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ZVEDENA_COLUMNS)
    yn = lambda b: "так" if b else "ні"
    for l in leads:
        w.writerow([
            l.manager, l.source_file, l.row_no, l.created.isoformat() if l.created else "",
            l.client, l.phone, l.channel or "", l.product,
            "" if l.amount is None else f"{l.amount:.2f}",
            l.stage or "", l.raw["stage"], l.step_text,
            l.step_date.isoformat() if l.step_date else "",
            yn(l.in_week), yn(l.is_duplicate), l.dup_of or "", yn(l.forgotten),
            "" if l.overdue_days is None else l.overdue_days,
            yn(l.in_contact_list), l.contact_rank or "", yn(l.manual), yn(l.due_today),
            "; ".join(l.shared_with), "; ".join(l.issues),
        ])
    return buf.getvalue()


# ------------------------------------------------------------- самоперевірка

def self_check(ctx: dict, zvedena_text: str, source_texts: dict) -> list[tuple[bool, str]]:
    """Промпт 9, п. 8, і правила brief.md."""
    zrows = list(csv.reader(io.StringIO(zvedena_text)))[1:]
    src_rows = sum(ctx["source_rows"].values())
    res = [(len(zrows) == src_rows,
            f"рядків у zvedena.csv ({len(zrows)}) = сума рядків трьох таблиць ({src_rows})")]
    contacts = ctx["contacts"]
    ok = total = 0
    for c in contacts:
        for l in c.leads:
            total += 1
            src = next(s for s in SOURCES if s.manager == l.manager)
            rows = list(csv.reader(io.StringIO(source_texts[l.manager], newline="")))
            header = [h.strip().lstrip("﻿") for h in rows[0]]
            r = rows[l.row_no - 1] if l.row_no - 1 < len(rows) else None
            ok += bool(r) and r[header.index(src.columns["client"])].strip() == l.client \
                and r[header.index(src.columns["phone"])].strip() == l.phone
    res.append((ok == total, f"кожен клієнт зі списку є у своїй таблиці ({ok}/{total})"))
    keys = [c.main.phone_key or id(c) for c in contacts]
    res.append((len(contacts) <= TOP_CONTACTS and len(keys) == len(set(keys)),
                f"у списку {len(contacts)} ≤ {TOP_CONTACTS} клієнтів, жоден не повторюється"))
    res.append((all(l.forgotten and not l.due_today for c in contacts for l in c.leads),
                "у списку лише забуті заявки, без «кроку на сьогодні»"))
    return res


# ------------------------------------------------------------------ архів

def history_name(report_date: date, existing: dict[str, str], text: str) -> str | None:
    """Ім'я нової архівної копії: zvit-<дата>.md, далі -2, -3, ...

    existing — наявні файли історії (ім'я -> вміст). Якщо точно такий самий звіт
    за цю дату вже є, нова версія не створюється (повертає None). Наявні файли
    ніколи не перезаписуються.
    """
    stem = f"zvit-{report_date.isoformat()}"
    versions = [f"{stem}.md"] + [f"{stem}-{n}.md" for n in range(2, len(existing) + 3)]
    for name in versions:
        if name not in existing:
            return name
        if existing[name] == text:
            return None
    raise RuntimeError("не вдалося підібрати ім'я архівної копії")


def write_history(history_dir: Path, report_date: date, text: str) -> tuple[Path | None, str]:
    history_dir.mkdir(parents=True, exist_ok=True)
    existing = {p.name: p.read_text(encoding="utf-8")
                for p in history_dir.glob(f"zvit-{report_date.isoformat()}*.md")}
    name = history_name(report_date, existing, text)
    if name is None:
        same = next(n for n, t in existing.items() if t == text)
        return history_dir / same, "без змін: така сама версія вже є в архіві"
    path = history_dir / name
    with open(path, "x", encoding="utf-8", newline="") as f:  # "x" — ніколи не перезаписує
        f.write(text)
    return path, "записано нову версію"


# ------------------------------------------------------------------ main

def build(source_texts: dict, period: Period, demo: bool = False) -> dict:
    """Повний розрахунок з текстів CSV (без роботи з диском) — зручно для тестів."""
    leads, source_rows, blanks = [], {}, {}
    for src in SOURCES:
        ls, blank = load_source(source_texts[src.manager], src, period.report_date)
        leads += ls
        source_rows[src.manager] = len(ls)
        blanks[src.manager] = blank
    unique = analyze(leads, period)
    all_contacts = contact_groups(unique)
    propagate_to_duplicates(leads)
    shared_groups: dict[str, list[Lead]] = {}
    for l in unique:
        if l.shared_with:
            shared_groups.setdefault(l.phone_key, []).append(l)
    ctx = {"period": period, "leads": leads, "unique": unique, "demo": demo,
           "source_rows": source_rows, "blank_rows": blanks,
           "all_contacts": all_contacts, "contacts": all_contacts[:TOP_CONTACTS],
           "shared_groups": shared_groups, "same_phone": same_phone_within_manager(unique)}
    ctx["stats"] = {m: manager_stats(m, leads, unique) for m in MANAGER_ORDER}
    return ctx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Тижневий звіт по заявках менеджерів.")
    ap.add_argument("--data", type=Path, default=ROOT / "data", help="папка з zayavky_*.csv")
    ap.add_argument("--reports", type=Path, default=ROOT / "reports", help="папка для звітів")
    ap.add_argument("--history", type=Path, default=ROOT / "history", help="папка архіву звітів")
    ap.add_argument("--brief", type=Path, default=ROOT / "brief.md", help="brief.md з датою звіту")
    args = ap.parse_args(argv)

    brief_text = args.brief.read_text(encoding="utf-8") if args.brief.exists() else None
    period = read_period(brief_text, date.today())
    demo = bool(brief_text and "штучні демонстраційні дані" in brief_text.lower())

    texts = {}
    for src in SOURCES:
        path = args.data / src.filename
        if not path.exists():
            print(f"ПОМИЛКА: немає файлу {path}", file=sys.stderr)
            return 1
        with open(path, encoding="utf-8", newline="") as f:
            texts[src.manager] = f.read()
    try:
        ctx = build(texts, period, demo)
    except DataError as e:
        print(f"ПОМИЛКА даних: {e}", file=sys.stderr)
        return 1

    zvit, zvedena = render_zvit(ctx), render_zvedena(ctx["leads"])
    checks = self_check(ctx, zvedena, texts)
    unique, stats = ctx["unique"], ctx["stats"]

    print(f"Тижневий звіт · дата звіту {d(period.report_date)} ({period.origin}) · "
          f"тиждень {d(period.week_start)}–{d(period.week_end)}")
    if demo:
        print("⚠ Дані в data/ — штучні демонстраційні.")
    print("\nПрочитано:")
    for src in SOURCES:
        s = stats[src.manager]
        blank = ctx["blank_rows"][src.manager]
        print(f"  {src.manager:<7} data/{src.filename:<20} рядків {s['rows']:>3}, точних копій {len(s['dups'])}, "
              f"унікальних заявок {len(s['unique'])}" + (f", порожніх рядків {blank}" if blank else ""))
    clients = len({l.phone_key for l in unique if l.phone_key})
    print(f"  Разом: {len(ctx['leads'])} рядків, {len(ctx['leads']) - len(unique)} точні копії, "
          f"{len(unique)} унікальних заявок, {clients} різних клієнтів (за телефоном)")

    per = lambda key: ", ".join(f"{m} {len(stats[m][key])}" for m in MANAGER_ORDER)
    tot = lambda key: sum(len(stats[m][key]) for m in MANAGER_ORDER)
    manual = sum(c.manual for c in ctx["contacts"])
    print("\nПоказники:")
    print(f"  заявок за тиждень:                {tot('week')} ({per('week')})")
    print(f"  договорів усього:                 {tot('contracts')} ({per('contracts')})")
    print(f"  договорів серед заявок тижня:     {tot('contracts_week')} ({per('contracts_week')})")
    print(f"  договорів без суми:               {tot('contracts_no_amount')} ({per('contracts_no_amount')})")
    print(f"  заявок без суми:                  {tot('amount_missing')} ({per('amount_missing')})")
    print(f"  порожніх стадій:                  {tot('empty_stage')} ({per('empty_stage')})")
    print(f"  забутих заявок:                   {tot('forgotten')} ({per('forgotten')})")
    print(f"  забутих клієнтів (за телефоном):  {len(ctx['all_contacts'])}")
    print(f"  у списку «Кому написати сьогодні»: {len(ctx['contacts'])} (ліміт {TOP_CONTACTS}), "
          f"з них потребують ручного рішення: {manual}")
    print(f"  чернеток клієнтам:                {len(ctx['contacts']) - manual}")
    print(f"  крок на сьогодні:                 {tot('due_today')} ({per('due_today')})")
    print(f"  клієнтів у кількох менеджерів:    {len(ctx['shared_groups'])}")
    issues = [l for l in unique if l.issues]
    print(f"  заявок із проблемами даних:       {len(issues)}")
    for l in issues:
        print(f"    {l.manager}, рядок {l.row_no}: {'; '.join(l.issues)}")

    print("\nСамоперевірка:")
    for ok, msg in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
    if not all(ok for ok, _ in checks):
        print("Самоперевірку не пройдено — звіти не записано.", file=sys.stderr)
        return 1

    args.reports.mkdir(parents=True, exist_ok=True)
    outputs = {"zvedena.csv": zvedena, "zvit.md": zvit,
               "managers.md": render_managers(ctx), "chernetky.md": render_chernetky(ctx)}
    print("\nЗаписано:")
    for name, text in outputs.items():
        path = args.reports / name
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"  {path}")
    hpath, status = write_history(args.history, period.report_date, zvit)
    print(f"  {hpath} — {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
