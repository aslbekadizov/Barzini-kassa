import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from telegram import Update
from telegram.ext import Application, ApplicationBuilder
from telegram.request import BaseRequest

import kassa


class FakeTelegramRequest(BaseRequest):
    """Telegramga haqiqiy xabar yubormasdan bot oqimini tekshirish."""

    def __init__(self):
        self.messages = []
        self.sent = []
        self.fail_chat_ids = set()
        self.rate_limit_after = None

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        action = url.rsplit("/", 1)[-1]
        if action == "getMe":
            result = {
                "id": 123456, "is_bot": True,
                "first_name": "Test", "username": "test_kassa_bot",
            }
        elif action == "sendMessage":
            params = request_data.parameters
            assert len(params["text"].encode("utf-16-le")) // 2 <= 4096
            if self.rate_limit_after == len(self.sent):
                self.rate_limit_after = None
                return 429, json.dumps({
                    "ok": False, "error_code": 429,
                    "description": "Too Many Requests: retry after 1",
                    "parameters": {"retry_after": 1},
                }).encode()
            if params["chat_id"] in self.fail_chat_ids:
                return 403, json.dumps({
                    "ok": False, "error_code": 403,
                    "description": "Forbidden: bot was blocked by the user",
                }).encode()
            self.sent.append(params)
            self.messages.append(params["text"])
            result = {
                "message_id": len(self.messages), "date": 1,
                "chat": {"id": params["chat_id"], "type": "private"},
                "text": params["text"],
            }
        else:
            raise AssertionError(f"Unexpected Telegram method: {action}")
        return 200, json.dumps({"ok": True, "result": result}).encode()


class BotTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "kassa.db"
        self.path_patch = patch.object(kassa, "DB_PATH", self.db_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        for name, value in (("CASHIER_ID", 1001), ("REPORT_CHAT_ID", 1002)):
            setting_patch = patch.object(kassa, name, value)
            setting_patch.start()
            self.addCleanup(setting_patch.stop)
        self.request = FakeTelegramRequest()
        builder = (
            ApplicationBuilder()
            .request(self.request)
            .get_updates_request(FakeTelegramRequest())
        )

        def capture_app(app, **kwargs):
            self.app = app
            self.assertFalse(kwargs["drop_pending_updates"])

        with (
            patch.object(kassa, "BOT_TOKEN", "123456:TEST"),
            patch.object(kassa, "ApplicationBuilder", return_value=builder),
            patch.object(Application, "run_polling", capture_app),
        ):
            kassa.main()

        await self.app.initialize()
        self.addAsyncCleanup(self.app.shutdown)
        self.errors = []

        async def record_error(update, context):
            self.errors.append(context.error)

        self.app.add_error_handler(record_error)
        kassa.add_transaction("income", "UZS", 500000, "Sinov")
        kassa.add_transaction("income", "USD", 20000, "Sinov dollar")
        kassa.add_transaction("expense", "UZS", -100000, "Sinov xarajat")
        kassa.add_exchange(10000, 1200000)
        self.original_rows = self.rows(self.db_path)
        self.update_id = 0

    def rows(self, path):
        with closing(sqlite3.connect(path)) as conn:
            return conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()

    def backups(self):
        return list(self.db_path.parent.glob("backups/*.db"))

    async def send(self, text, actor_id=None, chat_id=None):
        actor_id = kassa.CASHIER_ID if actor_id is None else actor_id
        chat_id = actor_id if chat_id is None else chat_id
        self.update_id += 1
        message = {
            "message_id": self.update_id, "date": 1,
            "chat": {"id": chat_id, "type": "private" if chat_id == actor_id else "group"},
            "from": {"id": actor_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        }
        if text.startswith("/"):
            message["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(text)}
            ]
        update = Update.de_json(
            {"update_id": self.update_id, "message": message}, self.app.bot
        )
        await self.app.process_update(update)
        self.assertEqual(self.errors, [])


class ResetTests(BotTestCase):
    async def test_confirm_resets_both_balances_and_backs_up_all_rows(self):
        kassa.add_transaction("income", "UZS", 500000, account="card")
        kassa.add_card_expense(100000, "Ali")
        self.original_rows = self.rows(self.db_path)
        await self.send("/reset")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_balance("UZS"), 0)
        self.assertEqual(kassa.get_balance("USD"), 0)
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(kassa.get_history(), [])
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.rows(backups[0]), self.original_rows)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertIn("Kassa nolga tushirildi", self.request.messages[-1])

    async def test_cancel_preserves_data_and_exits_reset(self):
        await self.send("/reset")
        await self.send("⬅️ Bekor qilish")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_cancel_command_preserves_data(self):
        await self.send("/reset")
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_unconfirmed_text_does_not_reset_or_record_expense(self):
        await self.send(kassa.RESET_CONFIRM_TEXT)
        await self.send("/reset")
        await self.send("benzin 150000")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])
        self.assertIn("tasdiqlash tugmasini", self.request.messages[-1])

    async def test_other_user_cannot_reset_or_confirm_cashier_request(self):
        await self.send("/reset", actor_id=999)
        self.assertIn("faqat kassir", self.request.messages[-1])
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT, actor_id=999)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.backups(), [])

    async def test_reset_interrupts_income_and_new_income_works_afterwards(self):
        await self.send("💰 Pul oldim")
        await self.send("🇺🇸 Dollar")
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("5000")
        self.assertEqual(kassa.get_balance("UZS"), 5000)
        self.assertEqual(kassa.get_balance("USD"), 0)
        self.assertEqual(len(kassa.get_history()), 1)

    async def test_backup_failure_preserves_data(self):
        (self.db_path.parent / "backups").write_text("Not a directory")
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertIn("Ma'lumotlar saqlandi", self.request.messages[-1])

    async def test_delete_failure_rolls_back_and_keeps_backup(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("""
                CREATE TRIGGER fail_reset BEFORE DELETE ON transactions
                BEGIN SELECT RAISE(ABORT, 'Simulated delete failure'); END
            """)
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.rows(self.backups()[0]), self.original_rows)
        self.assertIn("Ma'lumotlar saqlandi", self.request.messages[-1])


class NamedIncomeTests(BotTestCase):
    async def test_source_is_saved_shown_and_reported_for_both_cash_currencies(self):
        kassa.add_transaction("income", "UZS", 200000, account="card")
        cases = [
            ("🇺🇿 So'm", "Ali akadan 500000", "Ali akadan", "UZS", 500000,
             "💰 Naqd so'm", "500 000 so'm"),
            ("🇺🇸 Dollar", "Vali akadan 125.50", "Vali akadan", "USD", 12550,
             "💵 Naqd dollar", "$125.50"),
        ]
        for button, text, name, currency, amount, account_label, amount_text in cases:
            before = {code: kassa.get_balance(code) for code in ("UZS", "USD")}
            rows_before = self.rows(self.db_path)
            await self.send("💰 Pul oldim")
            await self.send(button)
            self.assertIn("Kimdan", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), rows_before)
            with patch.object(kassa, "now_text", return_value="2026-09-09 12:00:00"):
                await self.send(text)
            self.assertEqual(len(self.rows(self.db_path)), len(rows_before) + 1)
            for code in ("UZS", "USD"):
                self.assertEqual(kassa.get_balance(code), before[code] + (amount if code == currency else 0))
            self.assertEqual(kassa.get_balance("UZS", "card"), 200000)
            self.assertEqual(kassa.get_history()[0],
                ("2026-09-09 12:00:00", "income", currency, amount, f"Kimdan: {name}", "cash")
            )
            confirmation, report = self.request.sent[-2:]
            self.assertEqual(confirmation["chat_id"], kassa.CASHIER_ID)
            self.assertIn(f"Kimdan: {name}", confirmation["text"])
            self.assertIn(f"➕ {amount_text}", confirmation["text"])
            self.assertEqual(confirmation["reply_markup"], kassa.MAIN_KEYBOARD.to_dict())
            self.assertEqual(report["chat_id"], kassa.REPORT_CHAT_ID)
            self.assertEqual(report["text"],
                f"🟢 YANGI KIRIM\n\nHisob: {account_label}\n📝 Kimdan: {name}\n"
                f"➕ {amount_text}\n🕐 2026-09-09 12:00:00"
            )
            await self.send("/tarix")
            self.assertIn(f"Kimdan: {name}", self.request.messages[-1])
        await self.send("/stats")
        await self.send("📋 Barcha vaqt")
        self.assertNotIn("Kimdan:", self.request.messages[-1])
        self.assertIn("JAMI XARAJAT\nSo'm: 100 000 so'm\nDollar: $0", self.request.messages[-1])

    async def test_named_income_accepts_full_names_grouped_amounts_and_currency_suffixes(self):
        cases = [
            ("🇺🇿 So'm", "  Ali   akadan\n500 000  so'm  ", "Ali akadan", "UZS", 500000),
            ("🇺🇿 So'm", "12 sexdan 250_000 UZS", "12 sexdan", "UZS", 250000),
            ("🇺🇿 So'm", "Som 5000", "Som", "UZS", 5000),
            ("🇺🇸 Dollar", "G'ani akadan 12,50 $", "G'ani akadan", "USD", 1250),
            ("🇺🇸 Dollar", "Alidan 300$", "Alidan", "USD", 30000),
            ("🇺🇸 Dollar", "Alidan 0.01 USD", "Alidan", "USD", 1),
            ("🇺🇸 Dollar", "Alidan $ 50", "Alidan", "USD", 5000),
        ]
        for button, text, name, currency, amount in cases:
            await self.send("💰 Pul oldim")
            await self.send(button)
            await self.send(text)
            self.assertEqual(kassa.get_history()[0][1:],
                ("income", currency, amount, f"Kimdan: {name}", "cash")
            )
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + len(cases))

    async def test_invalid_named_income_preserves_money_and_allows_retry(self):
        cases = [
            ("🇺🇿 So'm", "UZS", "Alidan 500000", 500000, [
                "Alidan 0", "Alidan -500", "Alidan 300$", "Alidan 300 USD",
                "Alidan 9223372036854775808", "A" * 201 + " 5000",
            ]),
            ("🇺🇸 Dollar", "USD", "Alidan 300", 30000, [
                "Alidan 0", "Alidan -300", "Alidan 0.001$", "Alidan NaN",
                "Alidan Infinity", "Alidan 1e3", "Alidan 92233720368547758.08",
                "Alidan 500000 so'm", "Alidan 500000 UZS", "A" * 201 + " 300",
            ]),
        ]
        for button, currency, valid_text, amount, invalid_texts in cases:
            before = self.rows(self.db_path)
            report_count = sum(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent)
            await self.send("💰 Pul oldim")
            await self.send(button)
            for text in invalid_texts:
                await self.send(text)
                self.assertEqual(self.rows(self.db_path), before, text)
                self.assertIn("❌", self.request.messages[-1], text)
                self.assertNotIn("Masalan", self.request.messages[-1], text)
            self.assertEqual(sum(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent), report_count)
            await self.send(valid_text)
            self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)
            self.assertEqual(kassa.get_history()[0][1:],
                ("income", currency, amount, "Kimdan: Alidan", "cash")
            )

    async def test_separate_source_and_amount_for_all_accounts(self):
        for button, currency, amount, account in (
            ("🇺🇿 So'm", "UZS", "500000", "cash"),
            ("🇺🇸 Dollar", "USD", "12.50", "cash"),
            (kassa.CARD_BUTTON, "UZS", "200000", "card"),
        ):
            await self.send("💰 Pul oldim")
            await self.send(button)
            self.assertIn("Kimdan oldingiz?", self.request.messages[-1])
            before = self.rows(self.db_path)
            await self.send("Ali Valiyev")
            self.assertEqual(self.rows(self.db_path), before)
            self.assertIn("oldingiz?", self.request.messages[-1])
            await self.send("noto'g'ri summa")
            self.assertIn("❌", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
            await self.send(amount)
            row = kassa.get_history()[0]
            self.assertEqual(row[1:3], ("income", currency))
            self.assertEqual(row[4:6], ("Kimdan: Ali Valiyev", account))
            self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)

    async def test_source_is_not_reused_after_cancel_or_next_income(self):
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("Alidan")
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send("💰 Pul oldim")
        await self.send("🇺🇸 Dollar")
        await self.send("Validan 20")
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("500000")
        self.assertEqual(kassa.get_history()[0][1:], ("income", "UZS", 500000, "Pul olindi", "cash"))
        self.assertNotIn("Kimdan:", self.request.messages[-1])
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + 2)
        await self.send("benzin 150000")
        self.assertEqual(kassa.get_history()[0][1:4], ("expense", "UZS", -150000))

    async def test_other_person_cannot_submit_named_income_in_cashier_chat(self):
        await self.send("💰 Pul oldim", chat_id=-500)
        await self.send("🇺🇿 So'm", chat_id=-500)
        await self.send("Alidan 500000", actor_id=999, chat_id=-500)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertIn("faqat kassir", self.request.messages[-1])
        self.assertFalse(any(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent))


class CardAndStatisticsTests(BotTestCase):
    async def card_income(self, amount):
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send(str(amount))

    async def test_card_income_preserves_cash_and_dollars(self):
        before = (kassa.get_balance("UZS"), kassa.get_balance("USD"))
        await self.card_income(500000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        self.assertEqual((kassa.get_balance("UZS"), kassa.get_balance("USD")), before)
        cashier_messages = [m["text"] for m in self.request.sent if m["chat_id"] == kassa.CASHIER_ID]
        self.assertIn("Karta qoldiq: 500 000", cashier_messages[-1])
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("100000")
        self.assertEqual(kassa.get_balance("UZS"), before[0] + 100000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)

    async def test_account_selection_is_independent_between_chats(self):
        cash_before = kassa.get_balance("UZS")
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send("💰 Pul oldim", chat_id=-500)
        await self.send("🇺🇿 So'm", chat_id=-500)
        await self.send("500000")
        await self.send("100000", chat_id=-500)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        self.assertEqual(kassa.get_balance("UZS"), cash_before + 100000)
        self.assertEqual(kassa.get_balance("USD"), 10000)

    async def test_simultaneous_card_expenses_cannot_overdraw(self):
        kassa.add_transaction("income", "UZS", 100000, account="card")

        def spend(name):
            try:
                kassa.add_card_expense(80000, name)
                return True
            except kassa.InsufficientCardFunds:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(spend, ["Ali", "Vali"]))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(kassa.get_balance("UZS", "card"), 19200)

    async def test_card_expense_and_report_use_only_card_then_return_to_cash(self):
        await self.card_income(500000)
        cash_before = kassa.get_balance("UZS")
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 298000)
        self.assertEqual(kassa.get_balance("UZS"), cash_before)
        self.assertEqual(kassa.get_balance("USD"), 10000)
        report = self.request.sent[-1]
        self.assertEqual(report["chat_id"], kassa.REPORT_CHAT_ID)
        self.assertIn("Hisob: 💳 Karta", report["text"])
        self.assertNotIn("qoldiq", report["text"].lower())
        await self.send("benzin 150000")
        self.assertEqual(kassa.get_balance("UZS"), cash_before - 150000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 298000)
        self.assertIn("Hisob: 💰 Naqd so'm", self.request.messages[-1])

    async def test_cash_cannot_cover_missing_card_funds(self):
        await self.send("/kartadan")
        await self.send("Ali 200000")
        self.assertIn("yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)

    async def test_insufficient_card_funds_allow_retry_with_exact_balance(self):
        await self.card_income(101000)
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send("Ali 100000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)

    async def test_invalid_card_expenses_and_cancellation_preserve_money(self):
        await self.card_income(100000)
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        for value in ("Ali", "Ali 0", "Ali -100", "Ali " + "9" * 30):
            await self.send(value)
            self.assertEqual(self.rows(self.db_path), before)
        await self.send("⬅️ Bekor qilish")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send("0")
        await self.send("/cancel")
        self.assertEqual(self.rows(self.db_path), before)

    async def test_navigation_cancels_pending_card_expense(self):
        await self.card_income(500000)
        cash_before = kassa.get_balance("UZS")
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("/start")
        await self.send("benzin 50000")
        self.assertEqual(kassa.get_balance("UZS"), cash_before - 50000)
        self.assertEqual(kassa.get_balance("UZS", "card"), 500000)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send(kassa.STATISTICS_BUTTON)
        before = self.rows(self.db_path)
        await self.send("Ali 200000")
        self.assertEqual(self.rows(self.db_path), before)
        await self.send(kassa.BACK_BUTTON)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 298000)

    async def test_balance_history_and_menus_include_card(self):
        await self.card_income(500000)
        await self.send("/hisob")
        self.assertIn("Karta: 500 000", self.request.messages[-1])
        self.assertEqual("Karta: 500 000 so'm\nSo'm: 1 600 000 so'm\nDollar: $100", self.request.messages[-1])
        await self.send(kassa.BALANCE_BUTTON)
        self.assertEqual("Karta: 500 000 so'm\nSo'm: 1 600 000 so'm\nDollar: $100", self.request.messages[-1])
        await self.send("/tarix")
        self.assertIn("💳 Karta", self.request.messages[-1])
        self.assertIn("💵 Naqd", self.request.messages[-1])
        await self.send("/start")
        markup = str(self.request.sent[-1]["reply_markup"])
        self.assertIn(kassa.CARD_EXPENSE_BUTTON, markup)
        self.assertIn(kassa.STATISTICS_BUTTON, markup)
        self.assertIn(kassa.BALANCE_BUTTON, markup)

    async def test_card_and_statistics_are_cashier_only(self):
        for text in (kassa.CARD_EXPENSE_BUTTON, "/kartadan", kassa.STATISTICS_BUTTON, "/statistika"):
            await self.send(text, actor_id=999)
            self.assertIn("faqat kassir", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)

    async def test_statistics_list_each_expense_and_only_totals_and_current_balances(self):
        kassa.add_transaction("income", "UZS", 1000000, account="card")
        kassa.add_card_expense(400000, " BENZIN ")
        kassa.add_transaction("expense", "UZS", -150000, "benzin")
        kassa.add_transaction("expense", "USD", -5000, "Usta")
        expenses, totals, balances = kassa.get_statistics()
        self.assertEqual([row[1:] for row in expenses], [
            ("Sinov xarajat", "UZS", 100000, "cash"),
            (" BENZIN ", "UZS", 404000, "card"),
            ("benzin", "UZS", 150000, "cash"),
            ("Usta", "USD", 5000, "cash"),
        ])
        self.assertEqual(totals, {"UZS": 654000, "USD": 5000})
        self.assertEqual(balances, {
            ("cash", "UZS"): 1450000, ("card", "UZS"): 596000, ("cash", "USD"): 5000,
        })
        before = self.rows(self.db_path)
        await self.send("/statistika")
        await self.send("📋 Barcha vaqt")
        expected_entries = [
            "1. Sinov xarajat — 100 000 so'm (naqd)",
            "2.  BENZIN  — 404 000 so'm (karta)",
            "3. benzin — 150 000 so'm (naqd)",
            "4. Usta — $50 (naqd)",
        ]
        expected_list = "\n".join(
            entry + "\n" + row[0][:16] for entry, row in zip(expected_entries, expenses)
        )
        self.assertEqual(self.request.messages[-1],
            "📊 STATISTIKA — Barcha vaqt\n\n" + expected_list + "\n\n"
            "JAMI XARAJAT\nSo'm: 654 000 so'm\nDollar: $50\n\n"
            "HOZIRGI QOLDIQ\nNaqd so'm: 1 450 000 so'm\nKarta: 596 000 so'm\nDollar: $50"
        )
        self.assertEqual(self.rows(self.db_path), before)

    async def test_statistics_menu_periods_and_empty_report(self):
        kassa.reset_database()
        await self.send(kassa.STATISTICS_BUTTON)
        self.assertEqual(self.request.messages, ["Davrni tanlang:"])
        self.assertEqual(self.request.sent[-1]["reply_markup"], kassa.STATISTICS_KEYBOARD.to_dict())
        for button, (_, label) in kassa.STATISTICS_PERIODS.items():
            await self.send(button)
            self.assertEqual(self.request.messages[-1],
                f"📊 STATISTIKA — {label}\n\nBu davrda xarajat yo'q.\n\n"
                "JAMI XARAJAT\nSo'm: 0 so'm\nDollar: $0\n\n"
                "HOZIRGI QOLDIQ\nNaqd so'm: 0 so'm\nKarta: 0 so'm\nDollar: $0"
            )
        await self.send(kassa.BACK_BUTTON)
        self.assertIn("Kassa bot", self.request.messages[-1])

    async def test_statistics_send_all_expenses_and_full_long_notes_in_multiple_messages(self):
        kassa.reset_database()
        kassa.add_transaction("income", "UZS", 56100)
        names = [f"Xarajat {index}: " + "🚗" * 150 for index in range(30)]
        names.insert(8, "Juda uzun izoh: " + "🔧" * 2500)
        names.extend(["Takror xarajat", "Takror xarajat"])
        for index, name in enumerate(names, 1):
            kassa.add_transaction("expense", "UZS", -index * 100, name)
        before = self.rows(self.db_path)
        await self.send("/stats")
        start = len(self.request.messages)
        # Telegram temporarily throttles the second part; already sent parts must not repeat.
        self.request.rate_limit_after = len(self.request.sent) + 1
        with patch.object(kassa.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await self.send("📋 Barcha vaqt")
            sleep.assert_awaited_once()
            self.assertGreaterEqual(sleep.await_args.args[0], 1)
        chunks = self.request.messages[start:]
        self.assertGreater(len(chunks), 3)
        combined = "".join(chunks)
        previous_position = -1
        for index, name in enumerate(names, 1):
            entry = f"{index}. {name} — {kassa.format_uzs(index * 100)} so'm (naqd)"
            self.assertEqual(combined.count(entry), 1)
            position = combined.index(entry)
            self.assertGreater(position, previous_position)
            previous_position = position
        self.assertEqual(combined.count("JAMI XARAJAT"), 1)
        self.assertEqual(combined.count("HOZIRGI QOLDIQ"), 1)
        self.assertIn("JAMI XARAJAT\nSo'm: 56 100 so'm\nDollar: $0", chunks[-1])
        self.assertIn("Naqd so'm: 0 so'm", chunks[-1])
        for chunk in chunks:
            self.assertLessEqual(len(chunk.encode("utf-16-le")) // 2, 4000)
        self.assertEqual(self.rows(self.db_path), before)

    async def test_statistics_date_boundaries_use_tashkent_time(self):
        kassa.reset_database()
        dates = [
            ("2026-08-31 23:59:59", 1), ("2026-09-01 00:00:00", 10),
            ("2026-09-06 23:59:59", 100), ("2026-09-07 00:00:00", 1000),
            ("2026-09-07 23:59:59", 10000), ("2026-09-08 00:00:00", 100000),
            ("2026-10-01 00:00:00", 1000000),
        ]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executemany(
                "INSERT INTO transactions (created_at, kind, currency, amount, note, account) "
                "VALUES (?, 'income', 'UZS', ?, 'Sinov', 'card')", dates
            )
            conn.executemany(
                "INSERT INTO transactions (created_at, kind, currency, amount, note) "
                "VALUES (?, 'expense', 'UZS', -?, 'Sinov')", dates
            )
        now = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)
        cases = [
            ("today", 11000, dates[3:5]),
            ("month", 111110, dates[1:6]),
            ("all", 1111111, dates),
        ]
        for period, expected, included_dates in cases:
            expenses, totals, balances = kassa.get_statistics(period, now=now)
            self.assertEqual([(row[0], row[3]) for row in expenses], included_dates)
            self.assertEqual(totals, {"UZS": expected, "USD": 0})
            self.assertEqual(balances, {
                ("cash", "UZS"): -1111111, ("card", "UZS"): 1111111, ("cash", "USD"): 0,
            })

    async def test_empty_today_keeps_prior_balances_and_month_lists_prior_expenses(self):
        kassa.reset_database()
        with patch.object(kassa, "now_text", return_value="2026-09-08 12:00:00"):
            kassa.add_transaction("income", "UZS", 500000)
            kassa.add_transaction("income", "UZS", 200000, account="card")
            kassa.add_transaction("income", "USD", 30000)
            kassa.add_transaction("expense", "UZS", -50000, "Kecha benzin")
            kassa.add_transaction("expense", "USD", -10000, "Kecha furnitura")
        # At 20:00 UTC on September 8 it is already September 9 in Tashkent.
        with patch.object(kassa, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 9, 8, 20, tzinfo=timezone.utc)
            await self.send("/stats")
            await self.send("📅 Bugun")
            today = self.request.messages[-1]
            self.assertNotIn("Kecha", today)
            self.assertIn("Bu davrda xarajat yo'q.", today)
            self.assertIn("JAMI XARAJAT\nSo'm: 0 so'm\nDollar: $0", today)
            self.assertIn("Naqd so'm: 450 000 so'm\nKarta: 200 000 so'm\nDollar: $200", today)
            await self.send("🗓 Shu oy")
            month = self.request.messages[-1]
            self.assertIn("1. Kecha benzin — 50 000 so'm (naqd)", month)
            self.assertIn("2. Kecha furnitura — $100 (naqd)", month)
            self.assertIn("JAMI XARAJAT\nSo'm: 50 000 so'm\nDollar: $100", month)
            self.assertIn("Naqd so'm: 450 000 so'm\nKarta: 200 000 so'm\nDollar: $200", month)


class DollarExpenseTests(BotTestCase):
    async def test_dollar_expense_debits_only_dollars_and_updates_reports_and_statistics(self):
        kassa.add_transaction("income", "USD", 50000)
        kassa.add_transaction("income", "UZS", 200000, account="card")
        cash_before = kassa.get_balance("UZS")
        await self.send("Furnituraga 300$")
        self.assertEqual(kassa.get_balance("USD"), 30000)
        self.assertEqual(kassa.get_balance("UZS"), cash_before)
        self.assertEqual(kassa.get_balance("UZS", "card"), 200000)
        latest = kassa.get_history()[0]
        self.assertEqual(latest[1:], ("expense", "USD", -30000, "Furnituraga", "cash"))
        confirmation, report = self.request.sent[-2:]
        self.assertEqual(confirmation["chat_id"], kassa.CASHIER_ID)
        self.assertIn("Naqd dollar qoldiq: $300", confirmation["text"])
        self.assertEqual(report["chat_id"], kassa.REPORT_CHAT_ID)
        self.assertIn("Hisob: 💵 Naqd dollar", report["text"])
        self.assertIn("➖ $300", report["text"])
        self.assertNotIn("qoldiq", report["text"].lower())
        expenses, totals, balances = kassa.get_statistics()
        self.assertEqual(totals, {"UZS": 100000, "USD": 30000})
        self.assertEqual(expenses[-1][1:], ("Furnituraga", "USD", 30000, "cash"))
        self.assertEqual(balances[("cash", "USD")], 30000)
        await self.send("/tarix")
        self.assertIn("-$300", self.request.messages[-1])

    async def test_decimal_dollar_expenses_and_space_before_symbol_keep_exact_cents(self):
        before = kassa.get_balance("USD")
        cases = [("Furnituraga 12.50$", 1250), ("Usta 12,50 $", 1250), ("Mix 0.01$  ", 1)]
        spent = 0
        for text, cents in cases:
            await self.send(text)
            spent += cents
            self.assertEqual(kassa.get_balance("USD"), before - spent)
            self.assertEqual(kassa.get_history()[0][3], -cents)
        self.assertEqual(kassa.get_balance("UZS"), 1600000)

    async def test_invalid_dollar_amounts_neither_write_nor_send_reports(self):
        for amount in ("0", "-5", "0.001", "300.005", "NaN", "Infinity", "1e3", "92233720368547758.08"):
            await self.send(f"Furnituraga {amount}$")
            self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send("Furnituraga $")
        await self.send("300$")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertFalse(any(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent))

    async def test_card_mode_rejects_dollars_without_changing_any_balance(self):
        kassa.add_transaction("income", "UZS", 500000, account="card")
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Furnituraga 50$")
        self.assertEqual(self.rows(self.db_path), before)
        self.assertIn("Karta hisobi so'mda", self.request.messages[-1])
        self.assertFalse(any(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent))
        await self.send("Ali 150000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 348500)
        self.assertEqual(kassa.get_balance("USD"), 10000)

    async def test_expense_without_dollar_symbol_still_debits_som(self):
        await self.send("Furnituraga 30$")
        await self.send("benzin 150000")
        self.assertEqual(kassa.get_balance("USD"), 7000)
        self.assertEqual(kassa.get_balance("UZS"), 1450000)
        self.assertIn("Hisob: 💰 Naqd so'm", self.request.messages[-1])

    async def test_income_and_dollar_expense_use_updated_recipient(self):
        old_recipient = kassa.REPORT_CHAT_ID
        with patch.object(kassa, "REPORT_CHAT_ID", 1003):
            await self.send("Furnituraga 30$")
            await self.send("💰 Pul oldim")
            await self.send("🇺🇸 Dollar")
            await self.send("50")
        reports = [m for m in self.request.sent if m["chat_id"] == 1003]
        self.assertEqual(len(reports), 2)
        self.assertFalse(any(m["chat_id"] == old_recipient for m in self.request.sent))


class NotificationTests(BotTestCase):
    def reports(self):
        return [m["text"] for m in self.request.sent if m["chat_id"] == kassa.REPORT_CHAT_ID]

    async def test_all_income_accounts_send_only_transaction_details(self):
        cases = [
            ("🇺🇿 So'm", "500000", "💰 Naqd so'm", "500 000 so'm"),
            ("🇺🇸 Dollar", "100.50", "💵 Naqd dollar", "$100.50"),
            (kassa.CARD_BUTTON, "300000", "💳 Karta", "300 000 so'm"),
        ]
        with patch.object(kassa, "now_text", return_value="2026-09-07 15:00:00"):
            for button, amount, account, amount_text in cases:
                await self.send("💰 Pul oldim")
                await self.send(button)
                await self.send(amount)
                self.assertEqual(
                    self.reports()[-1],
                    f"🟢 YANGI KIRIM\n\nHisob: {account}\n"
                    f"➕ {amount_text}\n🕐 2026-09-07 15:00:00"
                )
        self.assertEqual(len(self.reports()), 3)
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + 3)

    async def test_cash_and_card_expenses_report_without_balances(self):
        kassa.add_transaction("income", "UZS", 500000, account="card")
        with patch.object(kassa, "now_text", return_value="2026-09-07 15:00:00"):
            await self.send("benzin 150000")
            await self.send(kassa.CARD_EXPENSE_BUTTON)
            await self.send("Ali 200000")
        self.assertEqual(self.reports(), [
            "🔴 YANGI XARAJAT\n\nHisob: 💰 Naqd so'm\n"
            "📝 benzin\n➖ 150 000 so'm\n🕐 2026-09-07 15:00:00",
            "🔴 YANGI XARAJAT\n\nHisob: 💳 Karta\n"
            "📝 Ali\n➖ 202 000 so'm\n🕐 2026-09-07 15:00:00",
        ])

    async def test_exchange_statistics_history_and_reset_do_not_send_reports(self):
        for text in ("/start", "/hisob", "/tarix", "/statistika", "📋 Barcha vaqt", kassa.BACK_BUTTON, "/id"):
            await self.send(text)
        await self.send("💵 $ maydalash")
        await self.send("10")
        await self.send("120000")
        await self.send("/reset")
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(self.reports(), [])

    async def test_invalid_cancelled_and_insufficient_transactions_do_not_report(self):
        await self.send("💰 Pul oldim")
        await self.send(kassa.CARD_BUTTON)
        await self.send("0")
        await self.send("/cancel")
        await self.send("benzin")
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 200000")
        await self.send("⬅️ Bekor qilish")
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(self.reports(), [])

    async def test_report_failure_keeps_income_and_allows_next_operation(self):
        self.request.fail_chat_ids.add(kassa.REPORT_CHAT_ID)
        before = kassa.get_balance("UZS")
        await self.send("💰 Pul oldim")
        await self.send("🇺🇿 So'm")
        await self.send("Alidan 500000")
        self.assertEqual(kassa.get_balance("UZS"), before + 500000)
        self.assertEqual(kassa.get_history()[0][4], "Kimdan: Alidan")
        self.assertIn("Kirim saqlandi", self.request.messages[-1])
        await self.send("benzin 150000")
        self.assertEqual(kassa.get_balance("UZS"), before + 350000)
        self.assertIn("Xarajat saqlandi", self.request.messages[-1])
        self.assertEqual(len(self.rows(self.db_path)), len(self.original_rows) + 2)
        self.assertEqual(self.reports(), [])

    async def test_report_recipient_cannot_view_history_or_make_changes(self):
        for command in ("/tarix", "/reset", "💰 Pul oldim", "/kartadan"):
            await self.send(command, actor_id=kassa.REPORT_CHAT_ID)
            self.assertIn("faqat kassir", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)


class MigrationTests(unittest.TestCase):
    def test_legacy_database_keeps_rows_balances_and_supports_card(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("""
                    CREATE TABLE transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                        kind TEXT NOT NULL, currency TEXT NOT NULL, amount INTEGER NOT NULL,
                        note TEXT, actor_id INTEGER
                    )
                """)
                conn.executemany(
                    "INSERT INTO transactions (created_at, kind, currency, amount, note, actor_id) "
                    "VALUES ('2026-09-01 12:00:00', ?, ?, ?, 'Eski', 1001)",
                    [("income", "UZS", 500000), ("expense", "UZS", -100000), ("income", "USD", 20000)]
                )
                original = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
            with patch.object(kassa, "DB_PATH", db_path):
                kassa.init_db()
                kassa.init_db()
                with closing(sqlite3.connect(db_path)) as conn:
                    migrated = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
                self.assertEqual(migrated, [row + ("cash", None) for row in original])
                self.assertEqual(kassa.get_clients(), [])
                self.assertEqual(kassa.get_balance("UZS"), 400000)
                self.assertEqual(kassa.get_balance("USD"), 20000)
                self.assertEqual(kassa.get_balance("UZS", "card"), 0)
                kassa.add_transaction("income", "UZS", 300000, account="card")
                kassa.add_card_expense(50000, "Ali")
                kassa.add_exchange(10000, 1200000)
                self.assertEqual(kassa.get_balance("UZS", "card"), 249500)
                self.assertEqual(kassa.get_balance("UZS"), 1600000)
                expenses, totals, balances = kassa.get_statistics()
                self.assertEqual(len(expenses), 2)
                self.assertEqual(totals, {"UZS": 150500, "USD": 0})
                self.assertEqual(balances, {
                    ("cash", "UZS"): 1600000, ("card", "UZS"): 249500, ("cash", "USD"): 10000,
                })


if __name__ == "__main__":
    unittest.main()


class NoOverdraftTests(BotTestCase):
    async def test_cash_dollar_client_and_other_expenses_fail_without_history_or_report(self):
        before = self.rows(self.db_path)
        reports = lambda: sum(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent)
        report_count = reports()
        for text in ("Material 1600001", "Material 100.01$"):
            await self.send(text)
            self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
        await self.send(kassa.OTHER_BUTTON)
        await self.send("Material 1600001")
        self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
        client = kassa.add_client("Ali")
        await self.send(kassa.CLIENTS_BUTTON)
        await self.send(client[1])
        await self.send("Material 2000000")
        for button in ("💵 Naqd so'm", kassa.CARD_BUTTON, "🇺🇸 Dollar"):
            await self.send(button)
            self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(reports(), report_count)
        await self.send("/cancel")
        await self.send("Material 1600000")
        await self.send("💵 Naqd so'm")
        self.assertEqual(kassa.get_balance("UZS"), 0)
        self.assertEqual(len(self.rows(self.db_path)), len(before) + 1)

    async def test_employee_insufficient_funds_all_accounts_can_retry(self):
        employee = kassa.add_employee("Ali")
        for button, amount in (("🇺🇿 So'm", "9999999"), ("🇺🇸 Dollar", "9999999"), (kassa.CARD_BUTTON, "1")):
            await self.send(kassa.EMPLOYEES_BUTTON)
            await self.send(employee[1])
            await self.send(kassa.EMPLOYEE_PAY_BUTTON)
            await self.send(button)
            before = self.rows(self.db_path)
            report_count = sum(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent)
            await self.send(amount)
            self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
            self.assertEqual(self.rows(self.db_path), before)
            self.assertEqual(kassa.get_employee_payments(employee[0]), [])
            self.assertEqual(sum(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent), report_count)

    async def test_concurrent_employee_and_expense_cannot_spend_same_money(self):
        employee = kassa.add_employee("Ali")
        for currency, account in (("UZS", "cash"), ("USD", "cash"), ("UZS", "card")):
            kassa.reset_database()
            kassa.add_transaction("income", currency, 100, account=account)
            def spend(employee_payment):
                try:
                    if employee_payment:
                        kassa.add_employee_payment(employee[0], currency, 80, account)
                    elif account == "card":
                        kassa.add_card_expense(80, "")
                    else:
                        kassa.add_transaction("expense", currency, -80, account=account)
                    return True
                except kassa.InsufficientFunds:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(spend, (False, True)))
            self.assertEqual(sorted(results), [False, True])
            self.assertEqual(kassa.get_balance(currency, account), 19 if account == "card" else 20)

    async def test_exchange_rechecks_funds_before_saving(self):
        await self.send("💵 $ maydalash")
        await self.send("100")
        kassa.add_transaction("expense", "USD", -10000, "Oldingi to'lov")
        before = self.rows(self.db_path)
        await self.send("1200000")
        self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
