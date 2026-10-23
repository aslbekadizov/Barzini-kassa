import sqlite3
from contextlib import closing
from unittest.mock import patch

import kassa
from test_kassa import BotTestCase


class EmployeeTests(BotTestCase):
    async def create(self, name):
        await self.send(kassa.EMPLOYEES_BUTTON)
        await self.send(kassa.ADD_EMPLOYEE_BUTTON)
        await self.send(name)
        return next(e for e in kassa.get_employees() if e[1] == name)

    async def select(self, employee, actor=None, chat=None):
        await self.send(kassa.EMPLOYEES_BUTTON, actor_id=actor, chat_id=chat)
        await self.send(employee[1], actor_id=actor, chat_id=chat)

    async def pay(self, currency, amount):
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send(currency)
        await self.send(amount)

    def reports(self):
        return [m['text'] for m in self.request.sent if m['chat_id'] == kassa.REPORT_CHAT_ID]

    async def test_three_accounts_debit_once_and_boss_can_read_employee_totals(self):
        kassa.add_transaction('income', 'UZS', 500000, account='card')
        employee = await self.create('Ali')
        await self.pay("🇺🇿 So'm", '100000')
        await self.pay('🇺🇸 Dollar', '12.50')
        await self.pay(kassa.CARD_BUTTON, '200000')
        self.assertEqual(kassa.get_balance('UZS'), 1500000)
        self.assertEqual(kassa.get_balance('USD'), 8750)
        self.assertEqual(kassa.get_balance('UZS', 'card'), 298000)
        self.assertEqual(len(kassa.get_employee_payments(employee[0])), 3)
        self.assertEqual(len(self.reports()), 3)
        for report, amount in zip(self.reports(), ("100 000 so'm", '$12.50', "202 000 so'm")):
            self.assertEqual(f'Aliga {amount} berildi.', report)
            self.assertNotIn('qoldiq', report.lower())
        await self.send('/start', actor_id=kassa.REPORT_CHAT_ID)
        self.assertEqual(self.request.sent[-1]['reply_markup'], kassa.BOSS_KEYBOARD.to_dict())
        await self.select(employee, actor=kassa.REPORT_CHAT_ID)
        text = self.request.messages[-1]
        self.assertIn("Jami so'm: 302 000 so'm", text)
        self.assertIn('Dollar: $12.50', text)
        self.assertNotIn('Sinov', text)
        self.assertNotIn('1 500 000', text)
        self.assertNotIn(kassa.EMPLOYEE_PAY_BUTTON, str(self.request.sent[-1]['reply_markup']))
        self.assertEqual(kassa.get_statement()[1]['UZS']['expense'], 100000)
        self.assertEqual(kassa.get_statistics()[1], {'UZS': 402000, 'USD': 1250})
        self.assertIn('Xodim: Ali', kassa.get_history()[0][4])

    async def test_boss_cannot_create_pay_or_access_other_financial_reports(self):
        employee = await self.create('Ali')
        before = self.rows(self.db_path)
        boss = kassa.REPORT_CHAT_ID
        await self.send(kassa.EMPLOYEES_BUTTON, actor_id=boss)
        self.assertNotIn(kassa.ADD_EMPLOYEE_BUTTON, str(self.request.sent[-1]['reply_markup']))
        await self.send(kassa.ADD_EMPLOYEE_BUTTON, actor_id=boss)
        await self.send('Begona', actor_id=boss)
        await self.select(employee, actor=boss)
        for text in (kassa.EMPLOYEE_PAY_BUTTON, '100000', '300$', kassa.CARD_BUTTON):
            await self.send(text, actor_id=boss)
            self.assertIn('faqat kassir', self.request.messages[-1])
        for command in ('/tarix', '/reset', '/boshqa'):
            await self.send(command, actor_id=boss)
            self.assertIn('faqat kassir', self.request.messages[-1])
        self.assertEqual(kassa.get_employees(), [employee])
        self.assertEqual(self.rows(self.db_path), before)
        await self.send('/xodimlar', actor_id=999)
        self.assertIn('faqat kassir va boshliq', self.request.messages[-1])

    async def test_selection_is_separate_for_boss_cashier_and_two_employees(self):
        ali = await self.create('Ali')
        vali = await self.create('Vali')
        await self.select(ali, chat=-500)
        await self.select(vali, actor=kassa.REPORT_CHAT_ID, chat=-500)
        await self.send('100000', chat_id=-500)
        self.assertEqual(len(kassa.get_employee_payments(ali[0])), 1)
        self.assertEqual(kassa.get_employee_payments(vali[0]), [])
        await self.select(vali)
        await self.send('20$')
        self.assertEqual(kassa.get_employee_payments(vali[0])[0][1:4], ('USD', 2000, 'cash'))
        await self.send(kassa.BACK_BUTTON)
        await self.send('Benzin 50000')
        self.assertEqual(len(kassa.get_employee_payments(vali[0])), 1)

    async def test_invalid_amounts_card_overdraft_cancel_and_retry(self):
        employee = await self.create('Ali')
        await self.send(kassa.EMPLOYEE_PAY_BUTTON)
        await self.send('bad 500000')
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send('🇺🇸 Dollar')
        for amount in ('0', '-5', 'NaN', '0.001', '92233720368547758.08'):
            await self.send(amount)
            self.assertEqual(self.rows(self.db_path), self.original_rows)
        await self.send('/cancel')
        self.assertIn('XODIM: Ali', self.request.messages[-1])
        await self.pay(kassa.CARD_BUTTON, '100000')
        self.assertIn('yetarli emas', self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        kassa.add_transaction('income', 'UZS', 101000, account='card')
        await self.send('100000')
        self.assertEqual(kassa.get_balance('UZS', 'card'), 0)
        self.assertEqual(len(kassa.get_employee_payments(employee[0])), 1)

    async def test_mapping_failure_rolls_back_expense_and_report_failure_keeps_payment(self):
        employee = await self.create('Ali')
        with self.assertRaises(sqlite3.IntegrityError):
            kassa.add_employee_payment(999, 'UZS', 100000)
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TRIGGER fail_mapping BEFORE INSERT ON employee_payments BEGIN SELECT RAISE(ABORT, 'fail'); END")
        await self.send('100000')
        self.assertIn('saqlanmadi', self.request.messages[-1])
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute('DROP TRIGGER fail_mapping')
        self.request.fail_chat_ids.add(kassa.REPORT_CHAT_ID)
        await self.send('100000')
        self.assertIn('Xarajat saqlandi', self.request.messages[-1])
        await self.send('10$')
        self.assertEqual(len(kassa.get_employee_payments(employee[0])), 2)
        self.assertEqual(kassa.get_balance('UZS'), 1500000)
        self.assertEqual(kassa.get_balance('USD'), 9000)

    async def test_reset_backs_up_payments_and_names_then_clears_totals(self):
        employee = await self.create('Ali')
        await self.send('100000')
        before = self.rows(self.db_path)
        await self.send('/reset')
        self.assertIn('Xodimlarga berilgan pullar tarixi ham tozalanadi', self.request.messages[-1])
        await self.send(kassa.RESET_CONFIRM_TEXT)
        self.assertEqual(kassa.get_employee_payments(employee[0]), [])
        self.assertEqual(kassa.get_employees(), [employee])
        self.assertEqual(self.rows(self.backups()[0]), before)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute('SELECT * FROM employee_payments').fetchall(), [])
        with closing(sqlite3.connect(self.backups()[0])) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM employee_payments').fetchone()[0], 1)
        await self.select(employee, actor=kassa.REPORT_CHAT_ID)
        self.assertIn("Jami so'm: 0 so'm", self.request.messages[-1])

    async def test_empty_migration_preserves_old_rows_and_pagination_names_and_long_history(self):
        self.assertEqual(kassa.get_employees(), [])
        kassa.init_db()
        self.assertEqual(self.rows(self.db_path), self.original_rows)
        self.assertEqual(kassa.get_employees(), [])
        employee = await self.create('Ali')
        self.assertEqual(kassa.add_employee(' ALI '), employee)
        for name in (' ', '👷', 'a' * 81):
            with self.assertRaises(ValueError):
                kassa.add_employee(name)
        for i in range(15):
            kassa.add_employee(f'Xodim {i:02}')
        await self.send(kassa.EMPLOYEES_BUTTON, actor_id=kassa.REPORT_CHAT_ID)
        await self.send(kassa.EMPLOYEE_NEXT, actor_id=kassa.REPORT_CHAT_ID)
        self.assertIn('Xodim 14', str(self.request.sent[-1]['reply_markup']))
        for i in range(30):
            kassa.add_employee_payment(employee[0], 'UZS', 1000, note=f'Tolov {i}: ' + '🔧' * 180)
        before = len(self.request.messages)
        await self.select(employee, actor=kassa.REPORT_CHAT_ID)
        chunks = self.request.messages[before + 1:]
        self.assertGreater(len(chunks), 2)
        for i in range(30):
            self.assertEqual(''.join(chunks).count(f'Tolov {i}:'), 1)
        self.assertIn("Jami so'm: 30 000 so'm", chunks[-1])

    async def test_boss_reads_clients_balance_statistics_without_write_access(self):
        client = kassa.add_client('Vali')
        kassa.add_transaction('income', 'UZS', 700000, client_id=client[0])
        kassa.add_transaction('expense', 'USD', -2500, 'Material', client_id=client[0])
        before = self.rows(self.db_path)
        boss = kassa.REPORT_CHAT_ID
        await self.send('/start', actor_id=boss)
        keyboard = str(self.request.sent[-1]['reply_markup'])
        for button in (kassa.CLIENTS_BUTTON, kassa.BALANCE_BUTTON, kassa.STATISTICS_BUTTON):
            self.assertIn(button, keyboard)
        await self.send(kassa.CLIENTS_BUTTON, actor_id=boss)
        self.assertNotIn(kassa.ADD_CLIENT_BUTTON, str(self.request.sent[-1]['reply_markup']))
        await self.send(kassa.ADD_CLIENT_BUTTON, actor_id=boss)
        self.assertIn('faqat kassir', self.request.messages[-1])
        await self.send(client[1], actor_id=boss)
        self.assertIn('700 000', self.request.messages[-1])
        self.assertNotIn(kassa.CLIENT_INCOME_BUTTON, str(self.request.sent[-1]['reply_markup']))
        for text in (kassa.CLIENT_INCOME_BUTTON, kassa.CLIENT_CARD_BUTTON, 'Material 100000'):
            await self.send(text, actor_id=boss)
            self.assertIn('faqat kassir', self.request.messages[-1])
        await self.send(kassa.CLIENT_REPORT_BUTTON, actor_id=boss)
        self.assertIn('Material', self.request.messages[-1])
        self.assertIn('$25', self.request.messages[-1])
        await self.send(kassa.BALANCE_BUTTON, actor_id=boss)
        for label in ('Karta:', "So'm:", 'Dollar:'):
            self.assertIn(label, self.request.messages[-1])
        self.assertEqual(self.request.sent[-1]['reply_markup'], kassa.BOSS_KEYBOARD.to_dict())
        for command in (kassa.STATISTICS_BUTTON, '/stats'):
            await self.send(command, actor_id=boss)
            for period in kassa.STATISTICS_PERIODS:
                await self.send(period, actor_id=boss)
                self.assertIn('JAMI XARAJAT', self.request.messages[-1])
                self.assertIn('HOZIRGI QOLDIQ', self.request.messages[-1])
        await self.send('/cancel', actor_id=boss)
        self.assertEqual(self.request.sent[-1]['reply_markup'], kassa.BOSS_KEYBOARD.to_dict())
        self.assertEqual(self.rows(self.db_path), before)
        for command in ('/hisob', '/stats', '/mijozlar'):
            await self.send(command, actor_id=999)
            self.assertIn('⛔', self.request.messages[-1])

    async def test_boss_client_navigation_does_not_change_cashier_shared_chat(self):
        ali = kassa.add_client('Ali')
        vali = kassa.add_client('Vali')
        await self.send(kassa.CLIENTS_BUTTON, chat_id=-500)
        await self.send(ali[1], chat_id=-500)
        for button in (kassa.CLIENTS_BUTTON, vali[1], kassa.CLIENT_REPORT_BUTTON,
                       kassa.BALANCE_BUTTON, kassa.STATISTICS_BUTTON, '📅 Bugun',
                       kassa.BACK_BUTTON):
            await self.send(button, actor_id=kassa.REPORT_CHAT_ID, chat_id=-500)
        await self.send('Material 100000', chat_id=-500)
        await self.send("💵 Naqd so'm", chat_id=-500)
        self.assertEqual(kassa.get_statement(ali[0])[1]['UZS']['expense'], 100000)
        self.assertEqual(kassa.get_statement(vali[0])[1]['UZS']['expense'], 0)
