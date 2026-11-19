import kassa
from test_kassa import BotTestCase


def rows_of(markup):
    return [[button["text"] for button in row] for row in markup["keyboard"]]


class LayoutTests(BotTestCase):
    def assert_two_columns(self, rows):
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(len(row), (1, 2), row)
        # Toq tugma yolg'iz qolishi mumkin, lekin tugmalar bir ustunda taxlanib qolmasin.
        for upper, lower in zip(rows, rows[1:]):
            self.assertFalse(len(upper) == 1 and len(lower) == 1, rows)

    def test_helper_splits_buttons_in_pairs(self):
        self.assertEqual(kassa.two_columns("a", "b", "c"), [["a", "b"], ["c"]])
        self.assertEqual(kassa.two_columns("a", "b", "c", "d"), [["a", "b"], ["c", "d"]])
        self.assertEqual(kassa.two_columns(), [])

    def test_static_keyboards_have_two_columns(self):
        names = [name for name in dir(kassa) if name.endswith("_KEYBOARD")
                 and hasattr(getattr(kassa, name), "keyboard") and name != "CANCEL_KEYBOARD"]
        self.assertGreaterEqual(len(names), 10)
        for name in names:
            with self.subTest(keyboard=name):
                self.assert_two_columns(rows_of(getattr(kassa, name).to_dict()))

    async def test_employee_and_client_lists_use_two_columns(self):
        for name in ("Ali", "Vali", "Sami", "Toshmat", "Karim"):
            kassa.add_employee(name)
            kassa.add_client(name)
        await self.send(kassa.EMPLOYEES_BUTTON)
        self.assert_two_columns(rows_of(self.request.sent[-1]["reply_markup"]))
        await self.send(kassa.BACK_BUTTON)
        await self.send(kassa.CLIENTS_BUTTON)
        self.assert_two_columns(rows_of(self.request.sent[-1]["reply_markup"]))

    async def test_employee_menu_and_client_window_use_two_columns(self):
        employee = kassa.add_employee("Ali")
        await self.send(kassa.EMPLOYEES_BUTTON)
        await self.send("Ali")
        self.assert_two_columns(rows_of(self.request.sent[-1]["reply_markup"]))
        self.assertEqual(employee[1], "Ali")
        await self.send(kassa.BACK_BUTTON)
        kassa.add_client("Nuri")
        await self.send(kassa.CLIENTS_BUTTON)
        await self.send("Nuri")
        self.assert_two_columns(rows_of(self.request.sent[-1]["reply_markup"]))
