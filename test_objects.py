import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import kassa
from test_kassa import BotTestCase


class ObjectTests(BotTestCase):
    def labels(self):
        return [[button["text"] for button in row]
                for row in self.request.sent[-1]["reply_markup"]["keyboard"]]

    async def open_client(self, client, **kwargs):
        await self.send(kassa.CLIENTS_BUTTON, **kwargs)
        await self.send(client[1], **kwargs)

    async def create_object(self, client, name="Oshxona", **kwargs):
        await self.open_client(client, **kwargs)
        await self.send(kassa.ADD_OBJECT_BUTTON, **kwargs)
        await self.send(name, **kwargs)
        return next(obj for obj in kassa.get_client_objects(client[0]) if obj[1] == name)

    async def spend(self, category="Mdf", amount="1000", account="💵 Naqd so'm", **kwargs):
        await self.send(kassa.OBJECT_EXPENSE_BUTTON, **kwargs)
        await self.send(category, **kwargs)
        await self.send(amount, **kwargs)
        await self.send(account, **kwargs)

    def reports(self):
        return [message for message in self.request.sent if message["chat_id"] == kassa.REPORT_CHAT_ID]

    async def test_client_and_object_buttons_are_side_by_side_and_paginated(self):
        clients = [kassa.add_client(f"Mijoz {index:02}") for index in range(13)]
        await self.send(kassa.CLIENTS_BUTTON)
        self.assertEqual(self.labels()[0], ["Mijoz 00", "Mijoz 01"])
        self.assertEqual(self.labels()[4], ["Mijoz 08", "Mijoz 09"])
        await self.send(kassa.NEXT_CLIENTS_BUTTON)
        self.assertEqual(self.labels()[0], ["Mijoz 10", "Mijoz 11"])
        self.assertEqual(self.labels()[1], ["Mijoz 12"])
        for index in range(13):
            kassa.add_client_object(clients[0][0], f"Obyekt {index:02}")
        await self.open_client(clients[0])
        self.assertEqual(self.labels()[0], ["🏠 Obyekt 00", "🏠 Obyekt 01"])
        await self.send(kassa.OBJECT_NEXT)
        self.assertEqual(self.labels()[0], ["🏠 Obyekt 10", "🏠 Obyekt 11"])
        await self.send("🏠 Obyekt 12")
        self.assertIn("Obyekt: Obyekt 12", self.request.messages[-1])
        await self.send(kassa.CLIENT_BACK_BUTTON)
        self.assertIn(kassa.ADD_OBJECT_BUTTON, str(self.labels()))

    async def test_eight_categories_record_once_and_identify_client_and_object(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        self.assertNotIn(kassa.CLIENT_CASH_BUTTON, str(self.labels()))
        for category in kassa.OBJECT_CATEGORIES:
            self.assertNotIn(category, str(self.labels()))
        original = self.rows(self.db_path)
        for index, category in enumerate(kassa.OBJECT_CATEGORIES, 1):
            await self.spend(category)
            self.assertEqual(len(self.rows(self.db_path)), len(original) + index)
            self.assertEqual(kassa.get_balance("UZS"), 1600000 - index * 1000)
            self.assertEqual(self.reports()[-1]["text"].count("Mijoz: Ali"), 1)
            self.assertIn("Obyekt: Oshxona", self.reports()[-1]["text"])
            await self.send("💵 Naqd so'm")
            self.assertEqual(len(self.rows(self.db_path)), len(original) + index)
        self.assertEqual(len(self.reports()), 8)
        self.assertEqual(len(kassa.get_object_expenses(client[0], obj[0])), 8)
        self.assertEqual(kassa.get_statement(client[0])[1]["UZS"]["expense"], 8000)
        self.assertIn("Obyekt: Oshxona", kassa.get_history()[0][4])
        self.assertIn("Obyekt: Oshxona", kassa.get_statistics()[0][-1][1])
        await self.send(kassa.OBJECT_REPORT_BUTTON)
        self.assertIn("8 000 so'm", self.request.messages[-1])
        for category in kassa.OBJECT_CATEGORIES:
            self.assertIn(category, self.request.messages[-1])
        self.assertEqual(len(self.reports()), 8)

    async def test_each_object_and_customer_have_separate_expenses(self):
        ali, vali = kassa.add_client("Ali"), kassa.add_client("Vali")
        kitchen = await self.create_object(ali)
        await self.spend("Mdf", "10000")
        bedroom = await self.create_object(ali, "Yotoqxona")
        await self.spend("Oyna", "20000")
        other = await self.create_object(vali)
        await self.spend("Tosh", "30000")
        self.assertNotEqual(kitchen[0], other[0])
        for client, obj, value in ((ali, kitchen, 10000), (ali, bedroom, 20000), (vali, other, 30000)):
            self.assertEqual(sum(row[3] for row in kassa.get_object_expenses(client[0], obj[0])), value)
        self.assertEqual(kassa.get_object_expenses(ali[0], other[0]), [])
        self.assertEqual(kassa.get_statement(ali[0])[1]["UZS"]["expense"], 30000)
        self.assertEqual(kassa.get_statement(vali[0])[1]["UZS"]["expense"], 30000)

    async def test_invalid_amount_cancel_and_insufficient_balance_can_retry(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        before = self.rows(self.db_path)
        await self.send("Begona xarajat 1000")
        self.assertIn("Tugmalardan", self.request.messages[-1])
        await self.send(kassa.OBJECT_EXPENSE_BUTTON)
        await self.send("Begona")
        self.assertIn("tugmalardan", self.request.messages[-1])
        await self.send("Mdf")
        for amount in ("0", "-1", "NaN", "0.001", "Xarajat 100", "9223372036854775808"):
            await self.send(amount)
            self.assertIn("❌", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
        await self.send("12.50")
        await self.send(kassa.CARD_BUTTON)
        self.assertIn("mos emas", self.request.messages[-1])
        await self.send("/cancel")
        self.assertIn("Obyekt: Oshxona", self.request.messages[-1])
        await self.send("🇺🇸 Dollar")
        self.assertEqual(self.rows(self.db_path), before)
        await self.spend("Oyna", "100.01", "🇺🇸 Dollar")
        self.assertIn("yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        kassa.add_transaction("income", "USD", 1)
        await self.send("🇺🇸 Dollar")
        self.assertEqual(kassa.get_balance("USD"), 0)
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0])[0][2:4], ("USD", 10001))

    async def test_card_commission_and_failed_database_write_are_atomic(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        kassa.add_transaction("income", "UZS", 101000, account="card")
        await self.spend("Furnitura", "100000", kassa.CARD_BUTTON)
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0])[0][3], 101000)
        await self.send(kassa.OBJECT_EXPENSE_BUTTON)
        await self.send("Kraska")
        await self.send("1000")
        before, reports = self.rows(self.db_path), len(self.reports())
        with patch.object(kassa, "add_transaction", side_effect=sqlite3.OperationalError("locked")):
            await self.send("💵 Naqd so'm")
        self.assertIn("saqlanmadi", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(len(self.reports()), reports)
        await self.send("💵 Naqd so'm")
        self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)

    async def test_wrong_owner_or_category_rolls_back_entire_transaction(self):
        ali, vali = kassa.add_client("Ali"), kassa.add_client("Vali")
        obj = kassa.add_client_object(ali[0], "Oshxona")
        before = self.rows(self.db_path)
        for owner, category in ((vali[0], "Mdf"), (ali[0], "Begona"), (ali[0], "Bambuk")):
            with self.assertRaises(ValueError):
                kassa.add_transaction("expense", "UZS", -1000, client_id=owner, object_id=obj[0], category=category)
            self.assertEqual(self.rows(self.db_path), before)
        kassa.add_transaction("income", "UZS", 1010, account="card")
        before = self.rows(self.db_path)
        with self.assertRaises(ValueError):
            kassa.add_card_expense(1000, "Mdf", client_id=vali[0], object_id=obj[0], category="Mdf")
        self.assertEqual(self.rows(self.db_path), before)

    async def test_reset_and_undo_preserve_objects_and_audit_associations(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        await self.spend()
        tid = self.rows(self.db_path)[-1][0]
        kassa.reverse_transaction(tid, kassa.CASHIER_ID)
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0]), [])
        with closing(sqlite3.connect(self.db_path)) as conn:
            audit = json.loads(conn.execute("SELECT original_rows FROM transaction_undo").fetchone()[0])[0]
        self.assertEqual((audit["object_id"], audit["category"]), (obj[0], "Mdf"))
        await self.spend("Tosh", "2000")
        before = self.rows(self.db_path)
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_client_objects(client[0]), [obj])
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0]), [])
        self.assertEqual(self.rows(self.backups()[0]), before)
        with closing(sqlite3.connect(self.backups()[0])) as conn:
            self.assertEqual(conn.execute("SELECT object_id, category FROM object_expenses").fetchall(), [(obj[0], "Tosh")])
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT * FROM object_expenses").fetchall(), [])

    async def test_boss_can_read_but_not_add_objects_or_expenses(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client, chat_id=-500)
        await self.spend(chat_id=-500)
        await self.open_client(client, actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        self.assertNotIn(kassa.ADD_OBJECT_BUTTON, str(self.labels()))
        await self.send("🏠 Oshxona", actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        self.assertNotIn(kassa.OBJECT_EXPENSE_BUTTON, str(self.labels()))
        await self.send(kassa.OBJECT_REPORT_BUTTON, actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        self.assertIn("1 000 so'm", self.request.messages[-1])
        before = self.rows(self.db_path)
        await self.send(kassa.OBJECT_EXPENSE_BUTTON, actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send("Mdf", actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send("Tosh", actor_id=999, chat_id=-500)
        self.assertEqual(self.rows(self.db_path), before)
        await self.spend("Oyna", "2000", chat_id=-500)
        self.assertEqual(sum(row[3] for row in kassa.get_object_expenses(client[0], obj[0])), 3000)

    async def test_names_are_normalized_and_objects_survive_reinitialization(self):
        client = kassa.add_client("Ali")
        await self.open_client(client)
        await self.send(kassa.ADD_OBJECT_BUTTON)
        for name in ("  ", "🏠", "X" * 81):
            await self.send(name)
            self.assertIn("❌", self.request.messages[-1])
        await self.send("  Yangi   obyekt ")
        obj = kassa.get_client_objects(client[0])[0]
        self.assertEqual(obj[1], "Yangi obyekt")
        self.assertEqual(kassa.add_client_object(client[0], "YANGI OBYEKT"), obj)
        await self.spend()
        before = self.rows(self.db_path)
        kassa.init_db()
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(kassa.get_client_objects(client[0]), [obj])
        self.assertEqual(len(kassa.get_object_expenses(client[0], obj[0])), 1)

    async def test_expense_page_shows_fixed_categories_in_two_columns(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        self.assertIn(kassa.OBJECT_EXPENSE_BUTTON, str(self.labels()))
        await self.send(kassa.OBJECT_EXPENSE_BUTTON)
        self.assertEqual(self.labels(), [
            ["Mdf", "Furnitura"], ["Kraska", "Oyna"], ["Alifrem", "Tosh"], ["Yolkra", "64 Dokon"],
            ["⬅️ Bekor qilish"],
        ])
        before = self.rows(self.db_path)
        for text in ("Bambuk", "Ijara 1000", kassa.OBJECT_EXPENSE_BUTTON):
            await self.send(text)
            self.assertIn("tugmalardan", self.request.messages[-1])
        await self.send("⬅️ Bekor qilish")
        self.assertIn("Obyekt: Oshxona", self.request.messages[-1])
        self.assertIn(kassa.OBJECT_EXPENSE_BUTTON, str(self.labels()))
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0]), [])

    async def test_main_menu_has_no_other_expenses_section(self):
        await self.send("/start")
        self.assertNotIn("Boshqa xarajat", str(self.request.sent[-1]["reply_markup"]))
        before = self.rows(self.db_path)
        await self.send("/boshqa")
        self.assertEqual(self.rows(self.db_path), before)

    async def test_report_still_lists_expenses_saved_under_old_categories(self):
        client = kassa.add_client("Ali")
        obj = await self.create_object(client)
        kassa.add_transaction("expense", "UZS", -5000, "Eski yozuv", client_id=client[0])
        tid = self.rows(self.db_path)[-1][0]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO object_expenses(transaction_id, object_id, category) VALUES (?, ?, 'Bambuk')",
                         (tid, obj[0]))
        await self.spend("Mdf", "1000")
        await self.send(kassa.OBJECT_REPORT_BUTTON)
        text = self.request.messages[-1]
        self.assertIn("Bambuk", text)
        self.assertIn("Mdf", text)
        self.assertIn("6 000 so'm", text)

    async def open_object(self, client, name="Oshxona", **kwargs):
        await self.open_client(client, **kwargs)
        await self.send(f"🏠 {name}", **kwargs)

    async def pay_employee(self, employee, amount="100000", currency="🇺🇿 So'm", **kwargs):
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON, **kwargs)
        await self.send(employee[1], **kwargs)
        await self.send(kassa.EMPLOYEE_PAY_BUTTON, **kwargs)
        await self.send(currency, **kwargs)
        await self.send(amount, **kwargs)

    def assert_two_columns(self):
        rows = self.labels()
        self.assertTrue(all(len(row) <= 2 for row in rows), rows)

    def payments(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT t.client_id, p.employee_id, p.object_id FROM employee_payments p "
                                "JOIN transactions t ON t.id = p.transaction_id ORDER BY t.id").fetchall()

    async def test_object_window_lists_employees_and_returns_to_object(self):
        client, ali = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        kassa.add_employee("Vali")
        await self.create_object(client)
        self.assertIn(kassa.OBJECT_EMPLOYEES_BUTTON, str(self.labels()))
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON)
        self.assertIn("Obyekt: Oshxona", self.request.messages[-1])
        self.assertIn("Mijoz: Nuri", self.request.messages[-1])
        self.assertEqual(self.labels()[0], ["Ali", "Vali"])
        self.assertIn(kassa.OBJECT_BACK_BUTTON, str(self.labels()))
        self.assert_two_columns()
        await self.send("Ali")
        self.assertIn("XODIM: Ali", self.request.messages[-1])
        for button in (kassa.EMPLOYEE_PAY_BUTTON, kassa.EMPLOYEE_REPORT_BUTTON,
                       kassa.OBJECT_EMPLOYEES_BUTTON, kassa.OBJECT_BACK_BUTTON):
            self.assertIn(button, str(self.labels()))
        self.assertNotIn(kassa.EMPLOYEES_BUTTON, str(self.labels()))
        self.assert_two_columns()
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON)
        self.assertEqual(self.labels()[0], ["Ali", "Vali"])
        await self.send(kassa.OBJECT_BACK_BUTTON)
        self.assertIn("Obyekt: Oshxona", self.request.messages[-1])
        self.assertIn(kassa.OBJECT_EXPENSE_BUTTON, str(self.labels()))
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON)
        await self.send("Ali")
        await self.send(kassa.OBJECT_BACK_BUTTON)
        self.assertIn(kassa.OBJECT_EXPENSE_BUTTON, str(self.labels()))
        self.assertEqual(ali[1], "Ali")

    async def test_payment_from_object_is_linked_and_visible_everywhere(self):
        client, employee = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        obj = await self.create_object(client)
        await self.pay_employee(employee)
        self.assertEqual(self.payments(), [(None, employee[0], obj[0])])
        self.assertEqual(kassa.get_balance("UZS"), 1500000)
        self.assertIn("Aliga 100 000 so'm berildi.", self.request.messages[-2])
        self.assertIn("Obyekt: Oshxona", self.request.messages[-2])
        self.assertEqual(self.reports()[-1]["text"],
                         "Aliga 100 000 so'm berildi.\n👤 Mijoz: Nuri\n🏠 Obyekt: Oshxona")
        self.assertEqual(kassa.get_employee_payments(employee[0])[0][5:], ("Oshxona", "Nuri"))
        self.assertIn("🏠 Nuri / Oshxona", kassa.get_history()[0][4])
        self.assertIn("🏠 Nuri / Oshxona", kassa.get_statistics()[0][-1][1])
        await self.send(kassa.EMPLOYEE_REPORT_BUTTON)
        self.assertIn("🏠 Nuri / Oshxona", self.request.messages[-1])
        await self.send(kassa.OBJECT_BACK_BUTTON)
        await self.send(kassa.OBJECT_REPORT_BUTTON)
        text = self.request.messages[-1]
        self.assertIn("XODIMLARGA BERILGAN PUL", text)
        self.assertIn("Ali — 100 000 so'm (naqd)", text)
        # Xodimga berilgan pul mijoz va obyekt xarajatlariga qo'shilmaydi.
        self.assertEqual(kassa.get_object_expenses(client[0], obj[0]), [])
        self.assertEqual(kassa.get_statement(client[0])[1]["UZS"]["expense"], 0)

    async def test_payments_from_main_menu_stay_without_object(self):
        client, employee = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        obj = await self.create_object(client)
        await self.pay_employee(employee, "1000")
        await self.send(kassa.BACK_BUTTON)
        await self.send(kassa.EMPLOYEES_BUTTON)
        self.assertNotIn(kassa.OBJECT_BACK_BUTTON, str(self.labels()))
        await self.send("Ali")
        self.assertNotIn(kassa.OBJECT_BACK_BUTTON, str(self.labels()))
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send("🇺🇿 So'm")
        await self.send("2000")
        self.assertEqual(self.reports()[-1]["text"], "Aliga 2 000 so'm berildi.")
        self.assertEqual([row[2] for row in self.payments()], [obj[0], None])
        await self.send(kassa.EMPLOYEE_REPORT_BUTTON)
        self.assertEqual(self.request.messages[-1].count("🏠 Nuri / Oshxona"), 1)

    async def test_dollar_and_card_payments_and_insufficient_funds_keep_the_object(self):
        client, employee = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        obj = await self.create_object(client)
        await self.pay_employee(employee, "9999999")
        self.assertIn("yetarli emas", self.request.messages[-1])
        self.assertEqual(self.payments(), [])
        await self.send("/cancel")
        self.assertIn(kassa.OBJECT_BACK_BUTTON, str(self.labels()))
        await self.pay_employee(employee, "12.50", "🇺🇸 Dollar")
        kassa.add_transaction("income", "UZS", 101000, account="card")
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON)
        await self.send("Ali")
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send(kassa.CARD_BUTTON)
        await self.send("100000")
        self.assertEqual([row[2] for row in self.payments()], [obj[0], obj[0]])
        await self.send(kassa.OBJECT_BACK_BUTTON)
        await self.send(kassa.OBJECT_REPORT_BUTTON)
        text = self.request.messages[-1]
        self.assertIn("Ali — $12.50 (naqd)", text)
        self.assertIn("Ali — 101 000 so'm (karta)", text)

    async def test_adding_an_employee_inside_an_object_keeps_the_object(self):
        client = kassa.add_client("Nuri")
        obj = await self.create_object(client)
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON)
        await self.send(kassa.ADD_EMPLOYEE_BUTTON)
        await self.send("Karim")
        self.assertIn(kassa.OBJECT_BACK_BUTTON, str(self.labels()))
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send("🇺🇿 So'm")
        await self.send("5000")
        self.assertEqual([row[2] for row in self.payments()], [obj[0]])

    async def test_boss_reads_object_payments_but_cannot_open_employee_list_there(self):
        client, employee = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        await self.create_object(client, chat_id=-500)
        await self.pay_employee(employee, chat_id=-500)
        boss = kassa.REPORT_CHAT_ID
        await self.open_object(client, actor_id=boss, chat_id=-500)
        self.assertNotIn(kassa.OBJECT_EMPLOYEES_BUTTON, str(self.labels()))
        before = self.payments()
        await self.send(kassa.OBJECT_EMPLOYEES_BUTTON, actor_id=boss, chat_id=-500)
        self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send(kassa.OBJECT_REPORT_BUTTON, actor_id=boss, chat_id=-500)
        self.assertIn("Ali — 100 000 so'm (naqd)", self.request.messages[-1])
        self.assertEqual(self.payments(), before)

    async def test_undo_describes_and_keeps_the_object_link_in_the_audit(self):
        client, employee = kassa.add_client("Nuri"), kassa.add_employee("Ali")
        obj = await self.create_object(client)
        await self.pay_employee(employee)
        tid = self.rows(self.db_path)[-1][0]
        description = kassa.undo_description(kassa.get_undo_rows(tid))
        self.assertIn("Ali · 🏠 Nuri / Oshxona", description)
        kassa.reverse_transaction(tid, kassa.CASHIER_ID)
        self.assertEqual(self.payments(), [])
        self.assertEqual(kassa.get_balance("UZS"), 1600000)
        with closing(sqlite3.connect(self.db_path)) as conn:
            audit = json.loads(conn.execute("SELECT original_rows FROM transaction_undo").fetchone()[0])[0]
        self.assertEqual((audit["employee_id"], audit["employee_object_id"]), (employee[0], obj[0]))

    async def test_old_database_gets_the_object_column_without_losing_payments(self):
        employee = kassa.add_employee("Ali")
        kassa.add_employee_payment(employee[0], "UZS", 1000)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("ALTER TABLE employee_payments RENAME TO new_payments")
            conn.execute("CREATE TABLE employee_payments (transaction_id INTEGER PRIMARY KEY "
                         "REFERENCES transactions(id) ON DELETE CASCADE, employee_id INTEGER NOT NULL "
                         "REFERENCES employees(id))")
            conn.execute("INSERT INTO employee_payments SELECT transaction_id, employee_id FROM new_payments")
            conn.execute("DROP TABLE new_payments")
        kassa.init_db()
        kassa.init_db()
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(employee_payments)")]
        self.assertIn("object_id", columns)
        self.assertEqual(kassa.get_employee_payments(employee[0])[0][5:], (None, None))
        with self.assertRaises(ValueError):
            kassa.add_employee_payment(employee[0], "UZS", 1000, object_id=9999)
