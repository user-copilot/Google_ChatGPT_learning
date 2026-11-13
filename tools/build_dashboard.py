#!/usr/bin/env python3
"""Автономний HTML-дашборд за результатами tools/zvit.py.

Джерела (лише читання):
  reports/zvedena.csv — усі показники рахуються з неї;
  reports/zvit.md     — дата звіту, звітний тиждень і позначка демо-даних.

Результат: dashboard/dashboard.html — один файл: HTML, CSS, SVG-графіки і трохи JS
(фільтр за менеджером). Жодних CDN, зовнішніх бібліотек, шрифтів чи мережевих запитів.
Файл перегенеровується при кожному запуску (як reports/).

Правила: відсутні значення не замінюються нулями — показуються як «невідомо»;
показники, яких немає в даних, не вигадуються. Однакові вхідні файли дають
побайтово однаковий HTML (немає поточного часу).

Тільки стандартна бібліотека Python 3.10+.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import re
import sys
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zvit import MANAGER_ORDER, OPEN_STAGES, STAGES, TOP_CONTACTS, ZVEDENA_COLUMNS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UNKNOWN = "невідомо"
YES, NO = "так", "ні"


class DataError(Exception):
    """Вхідні дані мають неочікувану структуру — дашборд не будується."""


# ------------------------------------------------------------------ читання

@dataclass
class Row:
    n: int                   # номер рядка в zvedena.csv (заголовок — 1)
    manager: str
    row_no: str
    created: str
    client: str
    phone: str
    channel: str
    product: str
    amount: Decimal | None
    stage: str               # єдиний етап або "" (порожньо / невідома стадія)
    stage_raw: str
    next_step: str
    next_step_date: str
    in_week: bool
    is_duplicate: bool
    duplicate_of_row: str
    forgotten: bool
    overdue_days: int | None
    in_contact_list: bool
    contact_rank: int | None
    manual: bool
    due_today: bool
    shared_with: str
    issues: str

    @property
    def phone_key(self) -> str:
        digits = re.sub(r"\D", "", self.phone)
        return digits[-9:] if len(digits) >= 9 else f"рядок {self.n}"


def _bool(value: str, col: str, n: int) -> bool:
    if value == YES:
        return True
    if value == NO:
        return False
    raise DataError(f"zvedena.csv, рядок {n}: колонка {col} має значення «{value}» замість «так»/«ні»")


def _int(value: str, col: str, n: int) -> int | None:
    if value == "":
        return None
    if not re.fullmatch(r"\d+", value):
        raise DataError(f"zvedena.csv, рядок {n}: колонка {col} — не ціле число «{value}»")
    return int(value)


def parse_zvedena(text: str) -> list[Row]:
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise DataError("zvedena.csv порожній: немає заголовка")
    missing = [c for c in ZVEDENA_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise DataError(f"zvedena.csv: немає колонок {missing}")
    rows = []
    for n, r in enumerate(reader, start=2):
        amount = None
        if r["amount"]:
            try:
                amount = Decimal(r["amount"])
            except InvalidOperation:
                raise DataError(f"zvedena.csv, рядок {n}: некоректна сума «{r['amount']}»") from None
        rows.append(Row(
            n=n, manager=r["manager"], row_no=r["row_no"], created=r["created"], client=r["client"],
            phone=r["phone"], channel=r["channel"], product=r["product"], amount=amount,
            stage=r["stage"], stage_raw=r["stage_raw"], next_step=r["next_step"],
            next_step_date=r["next_step_date"],
            in_week=_bool(r["in_week"], "in_week", n),
            is_duplicate=_bool(r["is_duplicate"], "is_duplicate", n),
            duplicate_of_row=r["duplicate_of_row"],
            forgotten=_bool(r["forgotten"], "forgotten", n),
            overdue_days=_int(r["overdue_days"], "overdue_days", n),
            in_contact_list=_bool(r["in_contact_list"], "in_contact_list", n),
            contact_rank=_int(r["contact_rank"], "contact_rank", n),
            manual=_bool(r["manual_decision"], "manual_decision", n),
            due_today=_bool(r["due_today"], "due_today", n),
            shared_with=r["shared_with"], issues=r["issues"],
        ))
    return rows


@dataclass
class Meta:
    report_date: str
    week: str
    demo: bool | None        # None — невідомо (немає zvit.md)
    zvit_week_count: int | None


def parse_zvit(text: str | None) -> Meta:
    if text is None:
        return Meta(UNKNOWN, UNKNOWN, None, None)
    d = re.search(r"^# Тижневий звіт · (\d{2}\.\d{2}\.\d{4})", text, re.M)
    w = re.search(r"За тиждень (\d{2}\.\d{2}\.\d{4})–(\d{2}\.\d{2}\.\d{4}) надійшло (\d+)", text)
    return Meta(
        report_date=d[1] if d else UNKNOWN,
        week=f"{w[1]}–{w[2]}" if w else UNKNOWN,
        demo="Штучні демонстраційні дані" in text,
        zvit_week_count=int(w[3]) if w else None,
    )


# --------------------------------------------------------------- розрахунок

def ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def compute(rows: list[Row]) -> dict:
    """Усі показники дашборда — лише з рядків zvedena.csv."""
    unique = [r for r in rows if not r.is_duplicate]
    managers = [m for m in MANAGER_ORDER if any(r.manager == m for r in rows)]
    managers += sorted({r.manager for r in rows} - set(managers))

    def stats(ls: list[Row]) -> dict:
        contracts = [r for r in ls if r.stage == "Договір"]
        refusals = [r for r in ls if r.stage == "Відмова"]
        return {
            "unique": len(ls),
            "week": sum(r.in_week for r in ls),
            "contracts": len(contracts),
            "contracts_week": sum(r.in_week for r in contracts),
            "refusals": len(refusals),
            "open": sum(r.stage in OPEN_STAGES for r in ls),
            "stage_unknown": sum(r.stage == "" for r in ls),
            "stages": Counter(r.stage or UNKNOWN for r in ls),
            "conv_all": ratio(len(contracts), len(ls)),
            "conv_closed": ratio(len(contracts), len(contracts) + len(refusals)),
            "contracts_sum": sum((r.amount for r in contracts if r.amount is not None), Decimal(0)),
            "contracts_no_amount": sum(r.amount is None for r in contracts),
            "forgotten": sum(r.forgotten for r in ls),
            "due_today": sum(r.due_today for r in ls),
        }

    channels = {}
    for ch in sorted({r.channel or UNKNOWN for r in unique}):
        ls = [r for r in unique if (r.channel or UNKNOWN) == ch]
        channels[ch] = {"week": sum(r.in_week for r in ls), "all": len(ls),
                        "contracts": sum(r.stage == "Договір" for r in ls),
                        "contracts_week": sum(r.stage == "Договір" and r.in_week for r in ls)}
    channel_order = sorted(channels, key=lambda c: (-channels[c]["all"], -channels[c]["week"], c))

    contacts: dict[int, list[Row]] = {}
    for r in unique:
        if r.in_contact_list:
            contacts.setdefault(r.contact_rank if r.contact_rank is not None else 10**6, []).append(r)
    forgotten_clients = len({r.phone_key for r in unique if r.forgotten})

    shared: dict[str, list[Row]] = {}
    for r in unique:
        if r.shared_with:
            shared.setdefault(r.phone_key, []).append(r)

    return {
        "rows": len(rows), "unique_n": len(unique),
        "duplicates": [r for r in rows if r.is_duplicate],
        "clients": len({r.phone_key for r in unique}),
        "total": stats(unique),
        "managers": managers,
        "by_manager": {m: stats([r for r in unique if r.manager == m]) for m in managers},
        "channels": channels, "channel_order": channel_order,
        "contacts": [contacts[k] for k in sorted(contacts)],
        "forgotten_clients": forgotten_clients,
        "due_today": [r for r in unique if r.due_today],
        "shared": list(shared.values()),
        "empty_stage": [r for r in unique if r.stage == "" and not r.stage_raw.strip()],
        "no_amount": [r for r in unique if r.amount is None],
        "issues": [r for r in unique if r.issues],
    }


# ---------------------------------------------------------------- форматування

def e(x) -> str:
    return html.escape(str(x), quote=True)


def pct(x: float | None) -> str:
    return UNKNOWN if x is None else f"{x * 100:.1f}".replace(".", ",") + " %"


def money(x: Decimal) -> str:
    return f"{int(x):,}".replace(",", " ") + " грн"


def iso_to_ua(s: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m[3]}.{m[2]}.{m[1]}" if m else (s or UNKNOWN)


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def nice_max(v: int) -> tuple[int, int]:
    """Верх шкали і крок для «круглих» поділок."""
    if v <= 0:
        return 1, 1
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000):
        if v / step <= 6:
            top = -(-v // step) * step
            return top, step
    step = 10 ** (len(str(v)) - 1)
    return -(-v // step) * step, step


def bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Горизонтальний стовпчик: квадратний біля осі, заокруглений кінець даних."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (f"M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}"
            f"a{r},{r} 0 0 1 {-r},{r}h{-(w - r):.1f}z")


# ------------------------------------------------------------------ графіки

STAGE_VARS = {"Нова": "--s1", "Прорахунок": "--s2", "Замір": "--s3", "Договір": "--s4",
              "Відмова": "--s5", UNKNOWN: "--s-unknown"}
DARK_TEXT_FILLS = {"Договір"}  # жовтий слот: підпис темним


def svg_channels(model: dict) -> str:
    order, ch = model["channel_order"], model["channels"]
    if not order:
        return '<p class="empty">Немає даних про канали.</p>'
    label_w, plot_w, band, bar_h = 130, 440, 46, 14
    top, step = nice_max(max(c["all"] for c in ch.values()))
    height = 28 + band * len(order) + 24
    sx = lambda v: label_w + plot_w * v / top
    out = [f'<svg class="chart" viewBox="0 0 {label_w + plot_w + 50} {height}" role="img" '
           f'aria-label="Заявки і договори за каналами залучення">']
    for t in range(0, top + 1, step):
        x = sx(t)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="20" x2="{x:.1f}" y2="{height - 22}"/>'
                   f'<text class="tick" x="{x:.1f}" y="{height - 6}" text-anchor="middle">{t}</text>')
    for i, name in enumerate(order):
        c = ch[name]
        y0 = 26 + i * band
        out.append(f'<text class="label" x="{label_w - 10}" y="{y0 + bar_h + 2}" text-anchor="end">{e(name)}</text>')
        for j, (key, var, title) in enumerate((("all", "--s1", "Усього заявок"),
                                              ("contracts", "--s2", "Договорів"))):
            y = y0 + j * (bar_h + 2)
            v = c[key]
            path = bar_path(label_w, y, sx(v) - label_w, bar_h)
            tip = f"{name}: {title.lower()} — {v}"
            if path:
                out.append(f'<path class="mark" d="{path}" style="fill:var({var})"><title>{e(tip)}</title></path>')
            out.append(f'<text class="value" x="{sx(v) + 6:.1f}" y="{y + bar_h - 3}">{v}</text>')
    out.append(f'<line class="axis" x1="{label_w}" y1="20" x2="{label_w}" y2="{height - 22}"/></svg>')
    return "".join(out)


def svg_stages(model: dict) -> str:
    managers = model["managers"]
    if not managers:
        return '<p class="empty">Немає даних про менеджерів.</p>'
    label_w, plot_w, band, bar_h, gap = 90, 480, 42, 24, 2
    height = band * len(managers) + 8
    out = [f'<svg class="chart" viewBox="0 0 {label_w + plot_w + 20} {height}" role="img" '
           f'aria-label="Стадії заявок за менеджерами">']
    for i, m in enumerate(managers):
        s = model["by_manager"][m]
        y = 8 + i * band
        out.append(f'<text class="label" x="{label_w - 10}" y="{y + bar_h / 2 + 5}" text-anchor="end">{e(m)}</text>')
        total = s["unique"]
        if total == 0:
            out.append(f'<text class="tick" x="{label_w}" y="{y + bar_h / 2 + 5}">немає заявок</text>')
            continue
        parts = [(st, s["stages"].get(st, 0)) for st in STAGES + (UNKNOWN,)]
        parts = [(st, v) for st, v in parts if v > 0]
        usable = plot_w - gap * (len(parts) - 1)
        x = label_w
        for k, (st, v) in enumerate(parts):
            w = usable * v / total
            last = k == len(parts) - 1
            shape = (f'<path class="mark" d="{bar_path(x, y, w, bar_h)}"' if last
                     else f'<rect class="mark" x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}"')
            tip = f"{m} · {st}: {v} з {total}"
            out.append(f'{shape} style="fill:var({STAGE_VARS[st]})"><title>{e(tip)}</title>'
                       f'{"</path>" if last else "</rect>"}')
            if w >= 22:
                cls = "inlabel dark" if st in DARK_TEXT_FILLS or st == UNKNOWN else "inlabel"
                out.append(f'<text class="{cls}" x="{x + w / 2:.1f}" y="{y + bar_h / 2 + 4.5}" '
                           f'text-anchor="middle">{v}</text>')
            x += w + gap
    out.append("</svg>")
    return "".join(out)


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:var({var})"></i>{e(name)}</span>' for name, var in items) + "</div>"


# ---------------------------------------------------------------------- HTML

CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;
--s5:#e87ba4;--s-unknown:#c3c2b7;--warn-bg:#fff4d6;--warn-ink:#5c4300;--crit:#d03b3b;--chip:#eef3fb}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;
--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s-unknown:#5f5e5a;--warn-bg:#3a2f12;--warn-ink:#fbe3a6;
--chip:#1f2a3a}.chart .inlabel.dark{fill:#fff}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header,main,footer{max-width:1180px;margin:0 auto;padding:0 20px}
header{padding-top:28px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:0 0 14px}
.sub{color:var(--ink2);margin:0}
.banner{margin:16px 0;padding:12px 16px;border-radius:10px;background:var(--warn-bg);color:var(--warn-ink);
border:1px solid var(--ring)}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:14px 0 4px}nav a{color:var(--ink2);text-decoration:none;
font-size:14px}nav a:hover{color:var(--ink);text-decoration:underline}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:20px;margin:18px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px}
.tile .v{font-size:30px;font-weight:650;line-height:1.15}.tile .k{color:var(--ink2);font-size:13px}
.tile .f{color:var(--muted);font-size:12px;margin-top:4px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:18px}
.grid2 .card{margin:0}.grid2 h3,.card h3{margin:0 0 10px;font-size:16px}
.chart{width:100%;max-width:680px;height:auto;display:block}.chart .grid{stroke:var(--grid);stroke-width:1}
.chart .axis{stroke:var(--axis);stroke-width:1}.chart .tick{fill:var(--muted);font-size:11px}
.chart .label{fill:var(--ink2);font-size:13px}.chart .value{fill:var(--ink);font-size:12px;font-variant-numeric:tabular-nums}
.chart .inlabel{fill:#fff;font-size:12px;font-weight:600}.chart .inlabel.dark{fill:#0b0b0b}
.chart .mark:hover{opacity:.82}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:0 0 10px;color:var(--ink2);font-size:13px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:13px;white-space:nowrap}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--ring);
color:var(--ink2)}.badge.crit{color:var(--crit);border-color:var(--crit)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}
.filters button{font:inherit;font-size:14px;padding:5px 14px;border-radius:999px;border:1px solid var(--ring);
background:var(--surface);color:var(--ink);cursor:pointer}
.filters button[aria-pressed=true]{background:var(--chip);border-color:var(--s1)}
.note{color:var(--muted);font-size:13px;margin:10px 0 0}.empty{color:var(--ink2);font-style:italic}
footer{color:var(--muted);font-size:13px;padding-bottom:36px}
ul.plain{margin:6px 0 0;padding-left:20px}
@media (max-width:640px){.grid2{grid-template-columns:1fr}h1{font-size:22px}.tile .v{font-size:26px}}
"""

JS = """
(function(){var btns=document.querySelectorAll('.filters button');
function apply(m){btns.forEach(function(b){b.setAttribute('aria-pressed',b.dataset.m===m?'true':'false')});
document.querySelectorAll('[data-managers]').forEach(function(el){
var list=el.dataset.managers.split('|');el.hidden=!(m==='*'||list.indexOf(m)>=0)})}
btns.forEach(function(b){b.addEventListener('click',function(){apply(b.dataset.m)})});})();
"""


def table(head: list[tuple[str, bool]], rows: list[tuple[list, list[str]]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    out = ['<div class="tw"><table><thead><tr>']
    out += [f'<th{" class=n" if num else ""}>{e(h)}</th>' for h, num in head]
    out.append("</tr></thead><tbody>")
    for cells, managers in rows:
        attr = f' data-managers="{e("|".join(managers))}"' if managers else ""
        out.append(f"<tr{attr}>" + "".join(
            f'<td{" class=n" if num else ""}>{c}</td>' for c, (_, num) in zip(cells, head)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def tile(value: str, key: str, foot: str = "") -> str:
    return (f'<div class="tile"><div class="v">{e(value)}</div><div class="k">{e(key)}</div>'
            + (f'<div class="f">{e(foot)}</div>' if foot else "") + "</div>")


def render_html(model: dict, meta: Meta, source_note: str) -> str:
    t, mgrs, bm = model["total"], model["managers"], model["by_manager"]
    warnings = []
    if meta.demo is True:
        warnings.append("⚠️ <b>Штучні демонстраційні дані.</b> Клієнти, телефони й суми вигадані; "
                        "це не реальні дані студії.")
    elif meta.demo is None:
        warnings.append("⚠️ Статус даних невідомий (немає reports/zvit.md). Не публікуйте реальні "
                        "персональні дані.")
    if meta.zvit_week_count is not None and meta.zvit_week_count != t["week"]:
        warnings.append(f"⚠️ reports/zvit.md ({meta.zvit_week_count} заявок тижня) і zvedena.csv "
                        f"({t['week']}) не збігаються — схоже, вони з різних запусків. Перезапустіть tools/zvit.py.")

    p = []
    p.append(f'<header><h1>Заявки меблевої студії · дашборд</h1>'
             f'<p class="sub">Дата звіту: <b>{e(meta.report_date)}</b> · звітний тиждень: '
             f'<b>{e(meta.week)}</b></p>')
    p += [f'<div class="banner" role="note">{w}</div>' for w in warnings]
    p.append('<nav aria-label="Розділи"><a href="#pokaznyky">Показники</a><a href="#menedzhery">Менеджери</a>'
             '<a href="#kanaly">Канали</a><a href="#komu-napysaty">Кому написати сьогодні</a>'
             '<a href="#krok-na-sohodni">Крок на сьогодні</a><a href="#dubli">Дублі та проблеми</a>'
             '<a href="#pro-dani">Про дані</a></nav>')
    if mgrs:
        p.append('<div class="filters" role="group" aria-label="Фільтр таблиць за менеджером">'
                 '<button type="button" data-m="*" aria-pressed="true">Усі менеджери</button>'
                 + "".join(f'<button type="button" data-m="{e(m)}" aria-pressed="false">{e(m)}</button>'
                           for m in mgrs) + "</div>")
    p.append("</header><main>")

    # 1. Основні показники
    p.append('<section id="pokaznyky" class="card"><h2>Основні показники</h2><div class="tiles">')
    p.append(tile(str(model["rows"]), "Рядків у таблицях", f"з них точних копій: {len(model['duplicates'])}"))
    p.append(tile(str(model["unique_n"]), "Унікальних заявок", f"різних клієнтів (за телефоном): {model['clients']}"))
    p.append(tile(str(t["week"]), "Заявок за тиждень", meta.week))
    p.append(tile(str(t["contracts"]), "Договорів (стадія на дату звіту)",
                  f"серед заявок тижня: {t['contracts_week']}"))
    p.append(tile(pct(t["conv_all"]), "Частка договорів серед заявок",
                  f"договори / унікальні заявки = {t['contracts']} / {t['unique']}"))
    p.append(tile(pct(t["conv_closed"]), "Частка договорів серед закритих",
                  f"договори / (договори + відмови) = {t['contracts']} / {t['contracts'] + t['refusals']}"))
    p.append(tile(str(model["forgotten_clients"]), "Забутих клієнтів",
                  f"у списку на сьогодні: {len(model['contacts'])} (ліміт {TOP_CONTACTS})"))
    p.append(tile(str(t["due_today"]), "Крок на сьогодні", "ще не прострочено"))
    p.append("</div>")
    p.append(f'<p class="note">Конверсія рахується за стадією на дату звіту: дати підписання договорів у '
             f'таблицях немає, тому це не «конверсія за тиждень». Відкриті заявки ({t["open"]}) ще можуть '
             f'змінити стадію; заявки з невідомою стадією ({t["stage_unknown"]}) входять до знаменника першого '
             f'показника і не входять до другого. Сума договорів відома: {money(t["contracts_sum"])}; '
             f'договорів без суми: {t["contracts_no_amount"]} (не рахуються як нуль).</p></section>')

    # 2. Менеджери
    p.append('<section id="menedzhery" class="card"><h2>Порівняння менеджерів</h2>')
    p.append(legend([(s, STAGE_VARS[s]) for s in STAGES + (UNKNOWN,)]))
    p.append(svg_stages(model))
    head = [("Менеджер", False), ("Заявок тижня", True), ("Унікальних заявок", True)] + \
           [(s, True) for s in STAGES] + [("Стадія невідома", True), ("Договорів серед заявок тижня", True),
                                         ("Частка договорів", True), ("Серед закритих", True),
                                         ("Сума договорів (відома)", True), ("Договорів без суми", True),
                                         ("Забутих заявок", True), ("Крок на сьогодні", True)]
    rows = []
    for m in mgrs:
        s = bm[m]
        rows.append(([e(m), s["week"], s["unique"]] + [s["stages"].get(st, 0) for st in STAGES]
                     + [s["stage_unknown"], s["contracts_week"], pct(s["conv_all"]), pct(s["conv_closed"]),
                        money(s["contracts_sum"]), s["contracts_no_amount"], s["forgotten"], s["due_today"]],
                     []))
    p.append(table(head, rows, "Немає даних про менеджерів."))
    p.append('<p class="note">Індивідуальна аналітика: кожна заявка рахується у свого менеджера; '
             'точні копії рядків не рахуються.</p></section>')

    # 3. Канали
    ch, order = model["channels"], model["channel_order"]
    p.append('<section id="kanaly" class="card"><h2>Заявки і договори за каналами</h2>')
    p.append(legend([("Усього заявок", "--s1"), ("Договорів", "--s2")]))
    p.append(svg_channels(model))
    no_contract = [c for c in order if ch[c]["contracts"] == 0]
    p.append(table([("Канал", False), ("Заявок тижня", True), ("Усього заявок", True), ("Договорів", True),
                    ("Договорів серед заявок тижня", True), ("Частка договорів", True)],
                   [([e(c), ch[c]["week"], ch[c]["all"], ch[c]["contracts"], ch[c]["contracts_week"],
                      pct(ratio(ch[c]["contracts"], ch[c]["all"]))], []) for c in order],
                   "Немає даних про канали."))
    if order:
        p.append(f'<p class="note">Канали без жодного договору: {e(", ".join(no_contract) or "немає")}.</p>')
    p.append("</section>")

    # 4. Кому написати сьогодні
    p.append(f'<section id="komu-napysaty" class="card"><h2>Кому написати сьогодні (до {TOP_CONTACTS})</h2>')
    rows = []
    for i, group in enumerate(model["contacts"], 1):
        g0 = group[0]
        mg = [r.manager for r in group]
        manual = any(r.manual for r in group)
        status = ('<span class="badge crit">потребує ручного рішення</span>' if manual
                  else '<span class="badge">чернетка в reports/chernetky.md</span>')
        rows.append(([i, e(g0.client), e(", ".join(mg)), e(g0.phone),
                      "<br>".join(e(f"{r.next_step} · {iso_to_ua(r.next_step_date)}") for r in group),
                      "<br>".join(e(r.stage or UNKNOWN) for r in group),
                      max((r.overdue_days or 0) for r in group) if all(r.overdue_days is not None for r in group)
                      else UNKNOWN, status], mg))
    p.append(table([("№", True), ("Клієнт", False), ("Менеджер", False), ("Телефон", False),
                    ("Прострочений крок", False), ("Стадія", False), ("Днів прострочення", True),
                    ("Статус", False)], rows, "Забутих клієнтів немає."))
    rest = model["forgotten_clients"] - len(model["contacts"])
    if rest > 0:
        p.append(f'<p class="note">Ще {rest} {plural(rest, "забутий клієнт", "забуті клієнти", "забутих клієнтів")} '
                 f'поза лімітом — у reports/managers.md і reports/zvedena.csv.</p>')
    p.append("</section>")

    # 5. Крок на сьогодні
    p.append(f'<section id="krok-na-sohodni" class="card"><h2>Крок на сьогодні ({e(meta.report_date)})</h2>')
    p.append(table([("Менеджер", False), ("Рядок", True), ("Клієнт", False), ("Крок", False), ("Стадія", False)],
                   [([e(r.manager), e(r.row_no), e(r.client), e(r.next_step), e(r.stage)], [r.manager])
                    for r in model["due_today"]], "Кроків на сьогодні немає."))
    p.append('<p class="note">Це не забуті клієнти: крок заплановано на дату звіту. Чернетки для них не '
             'створюються.</p></section>')

    # 6. Дублі та проблемні записи
    p.append('<section id="dubli" class="card"><h2>Дублі та проблемні записи</h2><div class="grid2">')
    p.append('<div class="card"><h3>Клієнти в кількох менеджерів</h3>' + table(
        [("Клієнт", False), ("Телефон", False), ("Менеджери", False)],
        [([e(g[0].client), e(g[0].phone), e(", ".join(r.manager for r in g))], [r.manager for r in g])
         for g in model["shared"]], "Немає.") +
        '<p class="note">Заявки рахуються в кожного менеджера; потрібно погодити, хто веде клієнта.</p></div>')
    p.append('<div class="card"><h3>Точні копії рядків</h3>' + table(
        [("Менеджер", False), ("Рядок", True), ("Повторює рядок", True), ("Клієнт", False)],
        [([e(r.manager), e(r.row_no), e(r.duplicate_of_row), e(r.client)], [r.manager])
         for r in model["duplicates"]], "Немає.") +
        '<p class="note">Не рахуються новими заявками.</p></div>')
    p.append('<div class="card"><h3>Порожня стадія (статус невідомий)</h3>' + table(
        [("Менеджер", False), ("Рядок", True), ("Клієнт", False)],
        [([e(r.manager), e(r.row_no), e(r.client)], [r.manager]) for r in model["empty_stage"]], "Немає.") +
        "</div>")
    p.append('<div class="card"><h3>Невідома сума</h3>' + table(
        [("Менеджер", False), ("Рядок", True), ("Клієнт", False), ("Стадія", False)],
        [([e(r.manager), e(r.row_no), e(r.client), e(r.stage or UNKNOWN)], [r.manager])
         for r in model["no_amount"]], "Немає.") +
        '<p class="note">Порожні суми не замінюються нулем і не входять до підсумків.</p></div>')
    p.append("</div>")
    p.append('<h3 style="margin-top:18px">Інші проблеми даних</h3>' + table(
        [("Менеджер", False), ("Рядок", True), ("Клієнт", False), ("Проблема", False)],
        [([e(r.manager), e(r.row_no), e(r.client), e(r.issues)], [r.manager]) for r in model["issues"]],
        "Некоректних дат, сум, стадій чи каналів не виявлено.") + "</section>")

    # 7. Про дані
    p.append('<section id="pro-dani" class="card"><h2>Про дані</h2><ul class="plain">'
             f'<li>Дата звіту: {e(meta.report_date)}; звітний тиждень: {e(meta.week)}.</li>'
             f'<li>Джерела: {source_note}.</li>'
             '<li>Усі цифри пораховані скриптами tools/zvit.py і tools/build_dashboard.py; нічого не вписано вручну.</li>'
             '<li>Відсутні значення показані як «невідомо» і не замінюються нулями.</li>'
             '<li>Нічого не надсилається: дашборд — локальний статичний файл без мережевих запитів.</li>'
             "</ul></section></main>")
    p.append('<footer>Згенеровано tools/build_dashboard.py. Перегенеровується при кожному запуску.</footer>')

    title = f"Дашборд заявок · {meta.report_date}"
    return ("<!DOCTYPE html>\n<html lang=\"uk\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
            "style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:\">"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body>"
            + "".join(p) + f"<script>{JS}</script></body></html>\n")


def display_path(path: Path) -> str:
    """Шлях для показу в HTML: відносно проєкту, без локальних абсолютних шляхів."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def build_html(zvedena_text: str, zvit_text: str | None, source_note: str = "reports/zvedena.csv") -> str:
    return render_html(compute(parse_zvedena(zvedena_text)), parse_zvit(zvit_text), e(source_note))


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Автономний HTML-дашборд за reports/zvedena.csv.")
    ap.add_argument("--zvedena", type=Path, default=ROOT / "reports" / "zvedena.csv")
    ap.add_argument("--zvit", type=Path, default=ROOT / "reports" / "zvit.md")
    ap.add_argument("--out", type=Path, default=ROOT / "dashboard" / "dashboard.html")
    args = ap.parse_args(argv)

    if not args.zvedena.exists():
        print(f"ПОМИЛКА: немає {display_path(args.zvedena)} — спершу запустіть tools/zvit.py.", file=sys.stderr)
        return 1
    with open(args.zvedena, encoding="utf-8", newline="") as f:
        zvedena_text = f.read()
    zvit_text = args.zvit.read_text(encoding="utf-8") if args.zvit.exists() else None
    sha = hashlib.sha256(zvedena_text.encode("utf-8")).hexdigest()[:12]
    note = f"{display_path(args.zvedena)} (SHA-256 {sha}…)" + (
        f", {display_path(args.zvit)}" if zvit_text is not None else f", {display_path(args.zvit)} — {UNKNOWN}, файлу немає")
    try:
        rows = parse_zvedena(zvedena_text)
    except DataError as err:
        print(f"ПОМИЛКА даних: {err}", file=sys.stderr)
        return 1
    model, meta = compute(rows), parse_zvit(zvit_text)
    page = render_html(model, meta, e(note))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(page)
    t = model["total"]
    print(f"Дашборд · дата звіту {meta.report_date} · тиждень {meta.week}")
    print(f"  рядків {model['rows']}, точних копій {len(model['duplicates'])}, унікальних заявок {model['unique_n']}, "
          f"клієнтів {model['clients']}")
    print(f"  заявок тижня {t['week']}, договорів {t['contracts']}, частка договорів {pct(t['conv_all'])}, "
          f"серед закритих {pct(t['conv_closed'])}")
    print(f"  кому написати сьогодні: {len(model['contacts'])}, забутих клієнтів {model['forgotten_clients']}, "
          f"крок на сьогодні {t['due_today']}")
    if meta.demo is None:
        print("  ⚠ немає reports/zvit.md: дата звіту і статус даних — невідомо")
    if meta.zvit_week_count is not None and meta.zvit_week_count != t["week"]:
        print("  ⚠ zvit.md і zvedena.csv не збігаються — перезапустіть tools/zvit.py", file=sys.stderr)
    print(f"Записано: {display_path(args.out)} ({len(page.encode('utf-8')) // 1024} КБ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
