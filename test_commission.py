import kassa
from test_kassa import BotTestCase


class CommissionTests(BotTestCase):
    async def test_transfer_checks_total_retries_once_and_reports_101000(self):
        kassa.add_transaction("income", "UZS", 100000, account="card")
        before = self.rows(self.db_path)
        await self.send(kassa.CARD_EXPENSE_BUTTON)
        await self.send("Ali 100000")
        self.assertIn("Balansda pul yetarli emas", self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), before)
        self.assertFalse(any(m["chat_id"] == kassa.REPORT_CHAT_ID for m in self.request.sent))
        kassa.add_transaction("income", "UZS", 1000, account="card")
        await self.send("Ali 100000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertEqual(self.rows(self.db_path)[-1][4], -101000)
        self.assertIn("101 000 so'm", self.request.messages[-1])
        self.assertIn("101 000 so'm", self.request.messages[-2])
        tid = self.rows(self.db_path)[-1][0]
        kassa.reverse_transaction(tid, kassa.CASHIER_ID)
        self.assertEqual(kassa.get_balance("UZS", "card"), 101000)

    async def test_employee_message_and_other_expense_include_commission(self):
        employee = kassa.add_employee("Ali")
        kassa.add_transaction("income", "UZS", 202000, account="card")
        await self.send(kassa.EMPLOYEES_BUTTON)
        await self.send(employee[1])
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send(kassa.CARD_BUTTON)
        await self.send("100000")
        self.assertEqual(self.request.messages[-1], "Aliga 101 000 so'm berildi.")
        self.assertEqual(kassa.get_employee_payments(employee[0])[0][2], 101000)
        await self.send(kassa.OTHER_BUTTON)
        await self.send(kassa.OTHER_CARD_BUTTON)
        await self.send("Material 100000")
        self.assertEqual(kassa.get_balance("UZS", "card"), 0)
        self.assertIn("101 000 so'm", self.request.messages[-1])
        self.assertEqual(kassa.get_statement()[1]["UZS"]["expense"], 201000)

    async def test_rounding_and_old_transactions_are_not_charged_again(self):
        for amount, total in ((1, 2), (99, 100), (100, 101), (101, 103), (100000, 101000)):
            self.assertEqual(kassa.card_total(amount), total)
        kassa.add_transaction("income", "UZS", 200000, account="card")
        kassa.add_transaction("expense", "UZS", -100000, account="card")
        before = self.rows(self.db_path)
        kassa.init_db()
        self.assertEqual(self.rows(self.db_path), before)
        self.assertEqual(kassa.get_balance("UZS", "card"), 100000)
