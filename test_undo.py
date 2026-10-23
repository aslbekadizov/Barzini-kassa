import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import kassa
from test_kassa import BotTestCase


class UndoTests(BotTestCase):
    async def select_transaction(self, tid):
        await self.send(kassa.UNDO_BUTTON)
        while True:
            buttons = self.request.sent[-1]["reply_markup"]["keyboard"]
            labels = [b["text"] if isinstance(b, dict) else b for row in buttons for b in row]
            label = next((label for label in labels if label.startswith(f"#{tid} ")), None)
            if label:
                await self.send(label)
                return
            self.assertIn(kassa.UNDO_NEXT, labels)
            await self.send(kassa.UNDO_NEXT)

    def audits(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute("SELECT original_rows FROM transaction_undo ORDER BY id").fetchall()

    async def test_cancel_then_reverse_client_expense_updates_all_reports_once(self):
        client = kassa.add_client("Ali")
        kassa.add_transaction("expense", "USD", -1250, "Material", client_id=client[0])
        tid = self.rows(self.db_path)[-1][0]
        before = self.rows(self.db_path)
        await self.select_transaction(tid)
        self.assertIn("Ali", self.request.messages[-1])
        self.assertIn("$12.50", self.request.messages[-1])
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), before)
        await self.select_transaction(tid)
        await self.send("yo'q")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertEqual(kassa.get_balance("USD"), 10000)
        self.assertEqual(kassa.get_statement(client[0])[0], [])
        self.assertEqual(kassa.get_statistics()[1]["USD"], 0)
        self.assertEqual(len(self.audits()), 1)
        archived = json.loads(self.audits()[0][0])[0]
        self.assertEqual((archived["id"], archived["client_id"], archived["amount"]), (tid, client[0], -1250))
        with self.assertRaises(ValueError):
            kassa.reverse_transaction(tid, kassa.CASHIER_ID)
        self.assertEqual(len(self.audits()), 1)

    async def test_employee_card_payment_reversal_restores_balance_and_employee_total(self):
        employee = kassa.add_employee("Vali")
        kassa.add_transaction("income", "UZS", 100000, account="card")
        kassa.add_employee_payment(employee[0], "UZS", 40000, "card")
        tid = self.rows(self.db_path)[-1][0]
        await self.select_transaction(tid)
        self.assertIn("Vali", self.request.messages[-1])
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertEqual(kassa.get_balance("UZS", "card"), 100000)
        self.assertEqual(kassa.get_employee_payments(employee[0]), [])
        self.assertEqual(json.loads(self.audits()[0][0])[0]["employee_id"], employee[0])

    async def test_spent_income_cannot_be_reversed_until_balance_is_sufficient(self):
        kassa.add_transaction("income", "UZS", 100000, account="card")
        tid = self.rows(self.db_path)[-1][0]
        kassa.add_card_expense(10000, "Material")
        before = self.rows(self.db_path)
        await self.select_transaction(tid)
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(self.audits(), [])
        kassa.add_transaction("income", "UZS", 10100, account="card")
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(len(self.audits()), 1)

    async def test_exchange_reversal_is_atomic_and_restores_both_accounts(self):
        pair = [r for r in self.rows(self.db_path) if r[2] == "exchange_out"][0]
        await self.select_transaction(pair[0])
        self.assertIn("Dollar maydalash", self.request.messages[-1])
        self.assertIn("Olingan so'm", self.request.messages[-1])
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertEqual(kassa.get_balance("USD"), 20000)
        self.assertEqual(kassa.get_balance("UZS"), 400000)
        self.assertEqual(len(json.loads(self.audits()[0][0])), 2)

    async def test_exchange_reversal_insufficient_and_missing_pair_leave_ledger_unchanged(self):
        pair = [r for r in self.rows(self.db_path) if r[2] == "exchange_out"][0]
        kassa.add_transaction("expense", "UZS", -1500000, "Material")
        before = self.rows(self.db_path)
        with self.assertRaises(kassa.InsufficientFunds):
            kassa.reverse_transaction(pair[0], kassa.CASHIER_ID)
        self.assertEqual(self.rows(self.db_path), before)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM transactions WHERE id = ?", (pair[0] + 1,))
        before = self.rows(self.db_path)
        with self.assertRaises(ValueError):
            kassa.reverse_transaction(pair[0], kassa.CASHIER_ID)
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(self.audits(), [])

    async def test_pagination_and_boss_cannot_reverse(self):
        tid = self.rows(self.db_path)[0][0]
        for _ in range(12):
            kassa.add_transaction("income", "UZS", 1)
        await self.select_transaction(tid)
        self.assertIn("500 000", self.request.messages[-1])
        before = self.rows(self.db_path)
        for actor in (kassa.REPORT_CHAT_ID, 999):
            await self.send("/qaytarish", actor_id=actor)
            self.assertIn("faqat kassir", self.request.messages[-1])
            await self.send(kassa.UNDO_CONFIRM_BUTTON, actor_id=actor)
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(self.audits(), [])

    async def test_concurrent_reversal_only_happens_once(self):
        tid = self.rows(self.db_path)[2][0]
        def reverse(_):
            try:
                kassa.reverse_transaction(tid, kassa.CASHIER_ID)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reverse, range(2))), [False, True])
        self.assertEqual(kassa.get_balance("UZS"), 1700000)
        self.assertEqual(len(self.audits()), 1)

    async def test_other_dollar_button_accepts_amount_without_symbol_and_retries(self):
        await self.send(kassa.OTHER_BUTTON)
        self.assertIn(kassa.OTHER_USD_BUTTON, str(self.request.sent[-1]["reply_markup"]))
        await self.send(kassa.OTHER_USD_BUTTON)
        before = self.rows(self.db_path)
        for text in ("Material", "Material 0", "Material 100.01"):
            await self.send(text)
            self.assertIn("❌", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
        await self.send("Material 12.50")
        self.assertEqual(kassa.get_balance("USD"), 8750)
        self.assertEqual(kassa.get_balance("UZS"), 1600000)
        self.assertEqual(kassa.get_statement()[1]["USD"]["expense"], 1250)
        self.assertIn("Hisob: 💵 Naqd dollar", self.request.messages[-1])
        await self.send(kassa.OTHER_USD_BUTTON)
        await self.send("/cancel")
        await self.send("Material 1000")
        self.assertEqual(kassa.get_balance("UZS"), 1599000)

    async def test_failed_exchange_delete_rolls_back_audit_and_both_rows(self):
        pair = [r for r in self.rows(self.db_path) if r[2] == "exchange_out"][0]
        before = self.rows(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("""CREATE TRIGGER fail_undo BEFORE DELETE ON transactions
                WHEN OLD.kind = 'exchange_in'
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        await self.select_transaction(pair[0])
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertIn("Qaytarilmadi", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(self.audits(), [])
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP TRIGGER fail_undo")
        await self.send(kassa.UNDO_CONFIRM_BUTTON)
        self.assertEqual(len(self.audits()), 1)

    async def test_split_income_can_reverse_one_currency_without_removing_other(self):
        client = kassa.add_client("Ali")
        kassa.add_split_client_income(client[0], 5000, 200000)
        usd = self.rows(self.db_path)[-2]
        kassa.reverse_transaction(usd[0], kassa.CASHIER_ID)
        self.assertEqual(kassa.get_balance("USD"), 10000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 200000)
        self.assertEqual(kassa.get_statement(client[0])[1]["USD"]["income"], 0)
        self.assertEqual(kassa.get_statement(client[0])[1]["UZS"]["income"], 200000)
