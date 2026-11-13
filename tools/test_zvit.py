"""Тести ключових розрахунків tools/zvit.py (лише стандартна бібліотека).

Запуск:  python3 -B -m unittest discover -s tools -p "test_*.py" -v

Тести працюють з текстами CSV у пам'яті і нічого не записують на диск.
Окремий клас перевіряє контрольні значення для демо-даних у data/ (лише читання).
"""

import csv
import io
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zvit  # noqa: E402

P = zvit.Period(date(2026, 11, 2), date(2026, 10, 26), date(2026, 11, 1), "тест")
OLENA_H = "Дата,Клієнт,Телефон,Джерело,Що замовляє,Сума,Етап,Коментар"
IGOR_H = "Коли,Ім'я,Тел.,Звідки прийшов,Виріб,Бюджет,Статус,Нотатки"
MARYNA_H = "дата_створення,клієнт_піб,телефон,канал_залучення,товар,сума_грн,стадія_угоди,примітка"


def texts(olena=(), igor=(), maryna=()):
    return {"Олена": "\n".join([OLENA_H, *olena]) + "\n",
            "Ігор": "\n".join([IGOR_H, *igor]) + "\n",
            "Марина": "\n".join([MARYNA_H, *maryna]) + "\n"}


def o_row(day="20.10.2026", name="Клієнт А", phone="+380 00 111 11 11", amount="50000",
          stage="Нова", note="передзвонити 25.10"):
    return f"{day},{name},{phone},Instagram,кухня,{amount},{stage},{note}"


def m_row(day="2026-10-20", name="Клієнт М", phone="+380 00 333 33 33", amount="50000.00",
          stage="НОВА", note="передзвонити 25.10"):
    return f"{day},{name},{phone},Facebook,кухня,{amount},{stage},{note}"


class ParseTests(unittest.TestCase):
    def test_created_formats(self):
        ref = date(2026, 11, 2)
        self.assertEqual(zvit.parse_created("26.10.2026", ref), (date(2026, 10, 26), None))
        self.assertEqual(zvit.parse_created("2026-10-28", ref), (date(2026, 10, 28), None))
        self.assertEqual(zvit.parse_created("27 жовт", ref), (date(2026, 10, 27), None))
        self.assertEqual(zvit.parse_created("1 лист", ref), (date(2026, 11, 1), None))
        self.assertEqual(zvit.parse_created("5 груд", ref)[0], date(2025, 12, 5))  # не пізніше звіту

    def test_created_invalid(self):
        ref = date(2026, 11, 2)
        for bad in ("32.10.2026", "2026-13-01", "вчора", "27 abc", ""):
            value, issue = zvit.parse_created(bad, ref)
            self.assertIsNone(value, bad)
            self.assertTrue(issue, bad)

    def test_amount_formats_and_no_zero_substitution(self):
        self.assertEqual(zvit.parse_amount("85000"), (Decimal(85000), None))
        self.assertEqual(zvit.parse_amount("85000.00"), (Decimal("85000.00"), None))
        self.assertEqual(zvit.parse_amount("85 тис"), (Decimal(85000), None))
        self.assertEqual(zvit.parse_amount(""), (None, None))          # порожньо — не нуль
        value, issue = zvit.parse_amount("багато")
        self.assertIsNone(value)
        self.assertIn("некоректна сума", issue)
        self.assertIsNone(zvit.parse_amount("-500")[0])

    def test_stage_dictionary(self):
        for raw, canon in [("Нова", "Нова"), ("новий", "Нова"), ("НОВА", "Нова"),
                           ("рахую", "Прорахунок"), ("РОЗРАХУНОК", "Прорахунок"),
                           ("заміряли", "Замір"), ("ЗАМІР", "Замір"),
                           ("підписали", "Договір"), ("УГОДА", "Договір"),
                           ("злився", "Відмова"), ("ВТРАЧЕНО", "Відмова")]:
            self.assertEqual(zvit.parse_stage(raw), (canon, None), raw)
        self.assertEqual(zvit.parse_stage(""), (None, None))
        self.assertIsNone(zvit.parse_stage("думає")[0])
        self.assertIn("невідома стадія", zvit.parse_stage("думає")[1])

    def test_step_date_from_comment(self):
        ref = date(2026, 11, 2)
        self.assertEqual(zvit.parse_step("передзвонити 28.10", date(2026, 10, 20), ref),
                         ("передзвонити", date(2026, 10, 28), None))
        self.assertEqual(zvit.parse_step("зателефонувати", date(2026, 10, 20), ref)[1:],
                         (None, "у коментарі немає дати кроку"))
        self.assertIsNone(zvit.parse_step("28.10 або 30.10", date(2026, 10, 20), ref)[1])
        self.assertEqual(zvit.parse_step("замір 05.01", date(2026, 12, 20), ref)[1], date(2027, 1, 5))
        self.assertIsNone(zvit.parse_step("замір 31.02", date(2026, 10, 1), ref)[1])

    def test_phone_key_ignores_formatting(self):
        self.assertEqual(zvit.phone_key("+380 00 760 91 82"), zvit.phone_key("380007609182"))
        self.assertEqual(zvit.phone_key("+380 00 760 91 82"), zvit.phone_key("000-760-91-82"))
        self.assertIsNone(zvit.phone_key("123"))


class DuplicateTests(unittest.TestCase):
    def test_exact_copy_is_duplicate_and_not_counted(self):
        row = m_row(day="2026-10-27")
        ctx = zvit.build(texts(maryna=[row, row]), P)
        leads = [l for l in ctx["leads"] if l.manager == "Марина"]
        self.assertEqual(len(leads), 2)
        self.assertEqual(leads[1].dup_of, 2)
        self.assertEqual(len(ctx["stats"]["Марина"]["unique"]), 1)
        self.assertEqual(len(ctx["stats"]["Марина"]["week"]), 1)  # дубль не нова заявка тижня

    def test_trailing_space_or_case_makes_different_lead(self):
        a = m_row()
        b = m_row(name="Клієнт М ")   # пробіл у кінці значення
        c = m_row(name="клієнт м")    # інший регістр
        ctx = zvit.build(texts(maryna=[a, b, c]), P)
        self.assertEqual(len(ctx["unique"]), 3)

    def test_quotes_and_line_endings_do_not_matter(self):
        a = m_row()
        b = '"2026-10-20","Клієнт М","+380 00 333 33 33","Facebook","кухня","50000.00","НОВА","передзвонити 25.10"'
        t = texts(maryna=[a, b])
        t["Марина"] = t["Марина"].replace("\n", "\r\n")
        ctx = zvit.build(t, P)
        self.assertEqual(len(ctx["unique"]), 1)
        self.assertEqual(len(ctx["leads"]), 2)

    def test_shared_client_two_leads_one_client(self):
        olena = [o_row(name="Левченко Роман", phone="+380 00 760 91 82", note="уточнити розміри 09.11")]
        igor = ["18 жовт,Роман Левченко,380007609182,тг,гардеробна,95 тис,заміряли,погодити проєкт 02.11"]
        ctx = zvit.build(texts(olena, igor), P)
        self.assertEqual(len(ctx["unique"]), 2)                       # дві заявки
        self.assertEqual(len({l.phone_key for l in ctx["unique"]}), 1)  # один клієнт
        self.assertEqual(len(ctx["shared_groups"]), 1)
        self.assertEqual(ctx["stats"]["Олена"]["shared"][0].shared_with, ["Ігор"])


class ForgottenTests(unittest.TestCase):
    def build_one(self, stage, note, maryna=False):
        if maryna:
            return zvit.build(texts(maryna=[m_row(stage=stage, note=note)]), P)["unique"][0]
        return zvit.build(texts(olena=[o_row(stage=stage, note=note)]), P)["unique"][0]

    def test_open_stage_overdue_is_forgotten(self):
        l = self.build_one("Нова", "передзвонити 29.10")
        self.assertTrue(l.forgotten)
        self.assertEqual(l.overdue_days, 4)

    def test_closed_stage_is_not_forgotten(self):
        self.assertFalse(self.build_one("Договір", "монтаж 29.10").forgotten)
        self.assertFalse(self.build_one("Відмова", "нагадати 29.10").forgotten)

    def test_empty_or_unknown_stage_is_not_forgotten(self):
        self.assertFalse(self.build_one("", "передзвонити 29.10", maryna=True).forgotten)
        l = self.build_one("думає", "передзвонити 29.10")
        self.assertFalse(l.forgotten)
        self.assertTrue(l.issues)

    def test_step_on_report_date_is_due_today_not_forgotten(self):
        l = self.build_one("Замір", "виїхати на замір 02.11")
        self.assertFalse(l.forgotten)
        self.assertTrue(l.due_today)

    def test_duplicate_of_forgotten_counted_once(self):
        row = m_row(note="передзвонити 29.10")
        ctx = zvit.build(texts(maryna=[row, row]), P)
        self.assertEqual(len(ctx["stats"]["Марина"]["forgotten"]), 1)
        self.assertEqual(len(ctx["all_contacts"]), 1)


class ContactListTests(unittest.TestCase):
    def test_order_tiebreak_and_limit(self):
        olena = [o_row(day=f"{10 + i}.10.2026", name=f"О{i}", phone=f"+380 00 100 10 {10 + i}",
                       note="передзвонити 30.10") for i in range(8)]
        igor = [f"{5 + i} жовт,І{i},+380 00 200 20 {10 + i},інста,кухня,50 тис,новий,передзвонити 2{i}.10"
                for i in range(5)]
        ctx = zvit.build(texts(olena, igor), P)
        contacts = ctx["contacts"]
        self.assertEqual(len(ctx["all_contacts"]), 13)
        self.assertEqual(len(contacts), 10)
        self.assertEqual([c.main.client for c in contacts[:5]], ["І0", "І1", "І2", "І3", "І4"])
        # однакове прострочення (3 дні) — раніша дата створення вище
        self.assertEqual([c.main.client for c in contacts[5:]], ["О0", "О1", "О2", "О3", "О4"])
        out = [l for l in ctx["unique"] if l.forgotten and not l.in_contact_list]
        self.assertEqual([l.client for l in out], ["О5", "О6", "О7"])
        managers_md = zvit.render_managers(ctx)
        self.assertIn("поза лімітом 10", managers_md)

    def test_client_overdue_in_two_managers_appears_once_without_draft(self):
        olena = [o_row(name="Спільний Клієнт", phone="+380 00 555 55 55", note="передзвонити 25.10")]
        igor = ["20 жовт,Клієнт Спільний,380005555555,тг,кухня,50 тис,рахую,обговорити прорахунок 28.10"]
        maryna = [m_row(name="Інший", phone="+380 00 666 66 66", note="передзвонити 30.10")]
        ctx = zvit.build(texts(olena, igor, maryna), P)
        self.assertEqual(len(ctx["contacts"]), 2)
        shared = ctx["contacts"][0]
        self.assertTrue(shared.manual)
        self.assertEqual(shared.managers, ["Олена", "Ігор"])
        self.assertEqual(shared.overdue_days, 8)
        drafts = zvit.render_chernetky(ctx)
        self.assertIn("потребує ручного рішення", drafts)
        self.assertNotIn("Це Олена", drafts)
        self.assertNotIn("Це Ігор", drafts)
        self.assertIn("Це Марина", drafts)
        self.assertEqual(len(ctx["stats"]["Олена"]["forgotten"]), 1)  # індивідуально — у кожного
        self.assertEqual(len(ctx["stats"]["Ігор"]["forgotten"]), 1)

    def test_draft_has_one_question_and_no_send(self):
        ctx = zvit.build(texts(olena=[o_row(note="надіслати прорахунок 25.10")]), P)
        text = zvit.draft_text(ctx["contacts"][0].main)
        self.assertEqual(text.count("?"), 1)
        self.assertIn("25.10", text)
        self.assertIn("Нічого не надіслано", zvit.render_chernetky(ctx))


class StructureTests(unittest.TestCase):
    def test_missing_column_is_error(self):
        t = texts()
        t["Ігор"] = "Коли,Ім'я,Тел.\n"
        with self.assertRaises(zvit.DataError):
            zvit.build(t, P)

    def test_zvedena_has_all_rows_and_marks(self):
        row = m_row(note="передзвонити 29.10")
        ctx = zvit.build(texts(olena=[o_row(note="уточнити 02.11")], maryna=[row, row]), P)
        rows = list(csv.DictReader(io.StringIO(zvit.render_zvedena(ctx["leads"]))))
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["is_duplicate"] for r in rows], ["ні", "ні", "так"])
        self.assertEqual(rows[0]["due_today"], "так")
        self.assertEqual(rows[1]["in_contact_list"], "так")
        self.assertEqual(rows[1]["contact_rank"], "1")

    def test_history_never_overwrites(self):
        dt = date(2026, 11, 2)
        self.assertEqual(zvit.history_name(dt, {}, "A"), "zvit-2026-11-02.md")
        self.assertIsNone(zvit.history_name(dt, {"zvit-2026-11-02.md": "A"}, "A"))
        self.assertEqual(zvit.history_name(dt, {"zvit-2026-11-02.md": "A"}, "B"), "zvit-2026-11-02-2.md")
        self.assertEqual(zvit.history_name(
            dt, {"zvit-2026-11-02.md": "A", "zvit-2026-11-02-2.md": "B"}, "C"), "zvit-2026-11-02-3.md")

    def test_period_from_brief(self):
        p = zvit.read_period("Дата звіту: **02.11.2026**\nЗвітний тиждень: **26.10.2026–01.11.2026**",
                             date(2030, 1, 1))
        self.assertEqual((p.report_date, p.week_start, p.week_end, p.origin),
                         (date(2026, 11, 2), date(2026, 10, 26), date(2026, 11, 1), "brief.md"))
        self.assertEqual(zvit.read_period(None, date(2026, 11, 4)).week_start, date(2026, 10, 26))


DATA = Path(__file__).resolve().parent.parent / "data"


@unittest.skipUnless(all((DATA / s.filename).exists() for s in zvit.SOURCES), "немає демо-даних")
class DemoDataTests(unittest.TestCase):
    """Контрольні значення з brief.md для демо-даних (seed 20261102)."""

    @classmethod
    def setUpClass(cls):
        t = {}
        for s in zvit.SOURCES:
            with open(DATA / s.filename, encoding="utf-8", newline="") as f:
                t[s.manager] = f.read()
        cls.ctx = zvit.build(t, P, demo=True)

    def test_counts(self):
        c = self.ctx
        self.assertEqual(len(c["leads"]), 77)
        self.assertEqual(len(c["leads"]) - len(c["unique"]), 2)
        self.assertEqual(len(c["unique"]), 75)
        self.assertEqual(len({l.phone_key for l in c["unique"]}), 74)

    def test_week_forgotten_due_today(self):
        s = self.ctx["stats"]
        self.assertEqual([len(s[m]["week"]) for m in zvit.MANAGER_ORDER], [9, 8, 10])
        self.assertEqual([len(s[m]["forgotten"]) for m in zvit.MANAGER_ORDER], [5, 5, 4])
        self.assertEqual([len(s[m]["due_today"]) for m in zvit.MANAGER_ORDER], [3, 1, 0])
        self.assertEqual([len(s[m]["empty_stage"]) for m in zvit.MANAGER_ORDER], [0, 0, 3])
        self.assertEqual([len(s[m]["contracts_no_amount"]) for m in zvit.MANAGER_ORDER], [1, 1, 1])

    def test_contact_list(self):
        contacts = self.ctx["contacts"]
        self.assertEqual(len(self.ctx["all_contacts"]), 14)
        self.assertEqual(len(contacts), 10)
        self.assertEqual(contacts[0].main.client, "Сергій Гнатюк")
        self.assertEqual(contacts[9].main.client, "Вовк Богдан")
        self.assertFalse(any(c.manual for c in contacts))


if __name__ == "__main__":
    unittest.main()
