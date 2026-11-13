"""Тести tools/build_dashboard.py (лише стандартна бібліотека).

Запуск:  python3 -B -m unittest discover -s tools -p "test_*.py" -v

Тести будують HTML у пам'яті й нічого не записують на диск.
"""

import re
import sys
import unittest
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dashboard as bd  # noqa: E402
import zvit  # noqa: E402

P = zvit.Period(date(2026, 11, 2), date(2026, 10, 26), date(2026, 11, 1), "тест")
HEADER = ",".join(zvit.ZVEDENA_COLUMNS)
SECTIONS = ["pokaznyky", "menedzhery", "kanaly", "komu-napysaty", "krok-na-sohodni", "dubli", "pro-dani"]
ZVIT_DEMO = ("# Тижневий звіт · 02.11.2026\n\n> ⚠️ Штучні демонстраційні дані (див. brief.md).\n\n"
             "## Резюме\nЗа тиждень 26.10.2026–01.11.2026 надійшло {n} нових заявок.\n")


def zrow(**kw):
    base = dict(manager="Олена", source_file="zayavky_olena.csv", row_no="2", created="2026-10-20",
                client="Клієнт А", phone="+380 00 111 11 11", channel="Instagram", product="кухня",
                amount="50000.00", stage="Нова", stage_raw="Нова", next_step="передзвонити",
                next_step_date="2026-11-05", in_week="ні", is_duplicate="ні", duplicate_of_row="",
                forgotten="ні", overdue_days="", in_contact_list="ні", contact_rank="", manual_decision="ні",
                due_today="ні", shared_with="", issues="")
    base.update(kw)
    return ",".join(f'"{base[c]}"' for c in zvit.ZVEDENA_COLUMNS)


def csv_text(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


class Balanced(HTMLParser):
    VOID = {"meta", "br", "line", "path", "rect", "input", "img", "link"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        self.ids += [v for k, v in attrs if k == "id"]
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"неочікуваний </{tag}>, стек {self.stack[-3:]}")
        else:
            self.stack.pop()


def check_html(test, page):
    p = Balanced()
    p.feed(page)
    p.close()
    test.assertEqual(p.errors, [])
    test.assertEqual(p.stack, [])
    return p


class StructureTests(unittest.TestCase):
    def test_all_sections_and_wellformed(self):
        page = bd.build_html(csv_text(zrow()), ZVIT_DEMO.format(n=0))
        p = check_html(self, page)
        for s in SECTIONS:
            self.assertIn(s, p.ids)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn('lang="uk"', page)
        self.assertIn("Штучні демонстраційні дані", page)
        self.assertIn("02.11.2026", page)

    def test_no_external_resources(self):
        page = bd.build_html(csv_text(zrow()), ZVIT_DEMO.format(n=0))
        for bad in ("http://", "https://", "<script src", "<link", "@import", "url(", "fetch(",
                    "XMLHttpRequest", "/Users/", "/private/"):
            self.assertNotIn(bad, page, bad)
        self.assertIn("default-src 'none'", page)

    def test_reproducible(self):
        t = csv_text(zrow(), zrow(row_no="3", client="Б", phone="+380 00 222 22 22", stage="Договір"))
        self.assertEqual(bd.build_html(t, ZVIT_DEMO.format(n=0)), bd.build_html(t, ZVIT_DEMO.format(n=0)))

    def test_html_escaping(self):
        page = bd.build_html(csv_text(zrow(client="<script>alert(1)</script>", issues="a & b")), None)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        check_html(self, page)


class MissingDataTests(unittest.TestCase):
    def test_header_only_renders_with_unknowns(self):
        page = bd.build_html(csv_text(), ZVIT_DEMO.format(n=0))
        check_html(self, page)
        self.assertIn("Забутих клієнтів немає.", page)
        self.assertIn("Немає даних про канали.", page)
        # конверсія при нульовому знаменнику — «невідомо», а не 0 %
        tiles = re.findall(r'<div class="v">(.*?)</div><div class="k">(.*?)</div>', page)
        conv = {k: v for v, k in tiles}
        self.assertEqual(conv["Частка договорів серед заявок"], "невідомо")
        self.assertEqual(conv["Частка договорів серед закритих"], "невідомо")

    def test_missing_zvit_md(self):
        page = bd.build_html(csv_text(zrow()), None)
        self.assertIn("Дата звіту: <b>невідомо</b>", page)
        self.assertIn("Статус даних невідомий", page)
        self.assertNotIn("Штучні демонстраційні дані.", page)

    def test_empty_amount_not_zero(self):
        rows = [zrow(stage="Договір", amount=""),
                zrow(row_no="3", client="Б", phone="+380 00 222 22 22", stage="Договір", amount="1000.00")]
        model = bd.compute(bd.parse_zvedena(csv_text(*rows)))
        self.assertEqual(model["total"]["contracts_no_amount"], 1)
        self.assertEqual(model["total"]["contracts_sum"], 1000)
        self.assertEqual(len(model["no_amount"]), 1)
        self.assertIsNone(model["no_amount"][0].amount)

    def test_empty_stage_is_unknown(self):
        model = bd.compute(bd.parse_zvedena(csv_text(zrow(stage="", stage_raw=""))))
        self.assertEqual(model["total"]["stage_unknown"], 1)
        self.assertEqual(len(model["empty_stage"]), 1)
        self.assertIsNone(model["total"]["conv_closed"])

    def test_missing_column_is_error(self):
        with self.assertRaises(bd.DataError):
            bd.parse_zvedena("manager,row_no\nОлена,2\n")

    def test_bad_boolean_is_error(self):
        with self.assertRaises(bd.DataError):
            bd.parse_zvedena(csv_text(zrow(in_week="yes")))

    def test_empty_file_is_error(self):
        with self.assertRaises(bd.DataError):
            bd.parse_zvedena("")

    def test_mismatch_with_zvit_md_is_flagged(self):
        page = bd.build_html(csv_text(zrow(in_week="так")), ZVIT_DEMO.format(n=5))
        self.assertIn("не збігаються", page)


class MetricTests(unittest.TestCase):
    def test_conversions_and_duplicates(self):
        rows = [zrow(stage="Договір"),
                zrow(row_no="3", client="Б", phone="+380 00 222 22 22", stage="Відмова"),
                zrow(row_no="4", client="В", phone="+380 00 333 33 33", stage="Нова"),
                zrow(row_no="5", client="В", phone="+380 00 333 33 33", stage="Нова",
                     is_duplicate="так", duplicate_of_row="4")]
        model = bd.compute(bd.parse_zvedena(csv_text(*rows)))
        self.assertEqual(model["rows"], 4)
        self.assertEqual(model["unique_n"], 3)
        self.assertEqual(len(model["duplicates"]), 1)
        self.assertAlmostEqual(model["total"]["conv_all"], 1 / 3)
        self.assertAlmostEqual(model["total"]["conv_closed"], 1 / 2)
        self.assertEqual(bd.pct(1 / 3), "33,3 %")

    def test_contact_list_order_and_manual_case(self):
        rows = [zrow(client="Спільний", phone="+380 00 555 55 55", forgotten="так", overdue_days="8",
                     in_contact_list="так", contact_rank="1", manual_decision="так", shared_with="Ігор"),
                zrow(manager="Ігор", source_file="zayavky_igor.csv", client="Спільний", phone="380005555555",
                     forgotten="так", overdue_days="5", in_contact_list="так", contact_rank="1",
                     manual_decision="так", shared_with="Олена"),
                zrow(row_no="9", client="Другий", phone="+380 00 666 66 66", forgotten="так", overdue_days="3",
                     in_contact_list="так", contact_rank="2")]
        model = bd.compute(bd.parse_zvedena(csv_text(*rows)))
        self.assertEqual([len(g) for g in model["contacts"]], [2, 1])
        self.assertEqual(model["forgotten_clients"], 2)
        page = bd.render_html(model, bd.parse_zvit(None), "тест")
        self.assertIn("потребує ручного рішення", page)
        self.assertIn('data-managers="Олена|Ігор"', page)


DATA = Path(__file__).resolve().parent.parent / "data"


@unittest.skipUnless(all((DATA / s.filename).exists() for s in zvit.SOURCES), "немає демо-даних")
class DemoDataTests(unittest.TestCase):
    """Дашборд з демо-даних: zvit.py будує zvedena і zvit.md у пам'яті, звідти — HTML."""

    @classmethod
    def setUpClass(cls):
        texts = {}
        for s in zvit.SOURCES:
            with open(DATA / s.filename, encoding="utf-8", newline="") as f:
                texts[s.manager] = f.read()
        ctx = zvit.build(texts, P, demo=True)
        cls.zvedena = zvit.render_zvedena(ctx["leads"])
        cls.zvit_md = zvit.render_zvit(ctx)
        cls.model = bd.compute(bd.parse_zvedena(cls.zvedena))
        cls.page = bd.build_html(cls.zvedena, cls.zvit_md)

    def test_key_numbers(self):
        m, t = self.model, self.model["total"]
        self.assertEqual((m["rows"], m["unique_n"], m["clients"]), (77, 75, 74))
        self.assertEqual((t["week"], t["contracts"], t["refusals"], t["stage_unknown"]), (27, 10, 8, 3))
        self.assertEqual(bd.pct(t["conv_all"]), "13,3 %")
        self.assertEqual(bd.pct(t["conv_closed"]), "55,6 %")
        self.assertEqual((len(m["contacts"]), m["forgotten_clients"], t["due_today"]), (10, 14, 4))
        self.assertEqual([m["by_manager"][x]["forgotten"] for x in zvit.MANAGER_ORDER], [5, 5, 4])

    def test_page(self):
        p = check_html(self, self.page)
        for s in SECTIONS:
            self.assertIn(s, p.ids)
        self.assertNotIn("не збігаються", self.page)
        self.assertIn("Сергій Гнатюк", self.page)
        self.assertIn("Штучні демонстраційні дані", self.page)


if __name__ == "__main__":
    unittest.main()
