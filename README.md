# Barzini kassa

Bu yangi bot uchun mustaqil loyiha nusxasi. Asos: https://github.com/aslbekadizov/Kassa
Asl repozitoriyga o‘zgartirish kiritilmaydi. Eski botning tokeni, bazasi va
sozlamalari bu nusxaga ko‘chirilmagan. Yangi bot uchun BotFather orqali alohida
bot yarating va uning tokenini shu papkadagi `.env` fayliga kiriting.

Telegram orqali naqd so'm, dollar va kartadagi pulni hisobga olish boti.
Ma'lumotlar mahalliy `kassa.db` faylida saqlanadi.

## Ishga tushirish

Python 3.10 yoki yangiroq versiya kerak.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

`.env` faylida sozlamalarni kiriting:

- `BOT_TOKEN` — BotFather bergan bot tokeni.
- `CASHIER_ID` — kassirning Telegram ID raqami.
- `REPORT_CHAT_ID` — kirim va xarajat xabarlarini oladigan odamning Telegram ID raqami.

```sh
sh run.sh
```

Bot ishlashi uchun ushbu jarayon ishlab turishi kerak. To'xtatish: `Ctrl+C`.
Hisobotni oladigan odam ham botga `/start` yuborishi kerak.
ID raqamini bilish uchun botga `/id` yuboring. Kassir ID raqami `0` bo'lsa, kassa amallari yopiq bo'ladi;
`.env` faylini yangilagach, botni qayta ishga tushiring.

Token, bazalar, zaxira nusxalari va loglar Git'ga qo'shilmaydi.

## Foydalanish

- `/start` — asosiy menyu.
- `💰 Pul oldim` — naqd so'm, dollar yoki `💳 Karta` hisobiga kirim kiritish.
- `👥 Mijozlar` yoki `/mijozlar` — mijoz qo'shish va uning alohida hisobini ochish.
- `🧾 Boshqa xarajatlar` yoki `/boshqa` — mijozga tegishli bo'lmagan xarajatlar.
- `💵 $ maydalash` — dollarni so'mga almashtirish.
- `benzin 150000` — asosiy menyudan naqd so'm xarajatini yozish.
- `Furnituraga 300$` — asosiy menyudan naqd dollar hisobidan 300 dollar xarajat yozish.
- `💳 Kartadan` yoki `/kartadan` — masalan, `Ali 200000` deb kartadan xarajat yozish.
- `📊 Statistika` yoki `/statistika` — bugun, shu oy yoki barcha vaqt bo'yicha hisobot.
- `💰 Balans` yoki `/hisob` — karta, naqd so'm va dollar qoldiqlari.
- `/tarix` — oxirgi 10 ta operatsiya, naqd yoki karta belgisi bilan.
- `/reset` — tasdiqlashdan keyin uchala hisob qoldig'i va tarixni tozalash. Avval `backups/` papkasiga baza zaxirasi olinadi.
- `/cancel` — joriy amalni bekor qilish.
- `/id` — Telegram ID raqami.

## Pul oldim

`💰 Pul oldim` tugmasidan keyin so'm yoki dollarni tanlab, kimdan olganingizni va
miqdorni bitta xabarda yozing:

- `🇺🇿 So'm` → `Alidan 500000` yoki `Ali akadan 500 000`: naqd so'mga 500 000 qo'shiladi.
- `🇺🇸 Dollar` → `Alidan 300`: dollar hisobiga $300 qo'shiladi.
- `🇺🇸 Dollar` → `Alidan 12.50$` yoki `Alidan 12,50 $`: $12.50 qo'shiladi.

Kimdan olingani tasdiqlash xabarida, tarixda va hisobot oluvchiga yuboriladigan
kirim xabarida ko'rinadi. Valyuta tanlangan tugma bilan belgilanadi.
Faqat summani yozish ham avvalgidek ishlaydi. Karta kirimida summani yozasiz.

## Xodimlar

`👷 Xodimlar` yoki `/xodimlar` orqali ro'yxatni oching. Kassir `➕ Xodim qo'shish`
tugmasini bosib ismni kiritadi. Eski yozuvlar xodimlarga avtomatik biriktirilmaydi.

Xodimni tanlang → `💸 Pul berish` → so'm, dollar yoki karta → summani yozing.
Mijozlar va xodimlar ro'yxatidagi tanlash tugmalarida faqat ism ko'rinadi.
Xodim oynasiga to'g'ridan-to'g'ri `100000` yozish naqd so'm, `50$` yozish dollar
to'lovini qayd etadi. Kartadan berilganda avval tegishli hisobni tanlang.
Har bir to'lov umumiy kassadan bir marta ayiriladi va o'sha xodimga jamlanadi.
Tanlangan hisobda pul yetarli bo'lmasa to'lov yozilmaydi.

Boshliqqa faqat `Aliga 100 000 so'm berildi.` kabi qisqa xabar yuboriladi.
`📒 Xodim hisobi` barcha to'lovlarni, naqd so'm, kartadan,
jami so'm va dollar summalarini ko'rsatadi. Valyutalar bir-biriga aylantirilmaydi.

`REPORT_CHAT_ID` dagi boshliq `/start` bosib `👷 Xodimlar` tugmasidan shu
hisobotlarni o'zi ko'ra oladi. Uning menyusida Mijozlar, Balans va Statistika ham bor:
mijozlarning kirim-xarajatlari, umumiy qoldiqlar va tanlangan davr xarajatlarini ko'radi.
Mijoz va xodim qo'shish, pul yozish va reset faqat kassirda qoladi.

`/cancel` kiritilayotgan to'lovni bekor qiladi. `/reset` tasdiqlansa xodimlarga
berilgan pullar tarixi ham tozalanadi, xodim nomlari qoladi. Avval olinadigan
baza zaxirasi xodimlar va ularning to'lovlarini ham saqlaydi.

## Mijozlar hisobi

Mijozlar ro'yxati bo'sh boshlanadi. Eski kirim va xarajatlar, hatto izohida mijoz
ismi bo'lsa ham, mijozlarga avtomatik biriktirilmaydi va o'zgartirilmaydi.

1. `👥 Mijozlar` → `➕ Mijoz qo'shish` → mijozning ismini yozing.
2. Ismni yozgach bot darhol kirim turini so'raydi: so'm, dollar, karta yoki `💵 Dollar + 💳 Karta`.
3. Kerakli hisobni tanlang va miqdorni yozing. `Dollar + Karta` bo'lsa, avval dollarni,
   keyin kartaga tushgan so'mni yozasiz. Masalan: `300` dollar, keyin `500000` so'm karta.
4. Mijoz oynasiga xarajat nomi va summani yozing yoki `💸 Xarajat yozish`ni bosing.
5. Keyin `💵 Naqd so'm`, `💳 Karta` yoki `🇺🇸 Dollar`ni tanlang.
   Xarajat faqat hisob tanlangach saqlanadi va shu hisobdan ayriladi.
   Dollar tanlansa yozilgan summa dollar hisoblanadi; `$` belgisi shart emas.
   Tanlashdan oldin bekor qilinsa, pul ayrilmaydi.
6. `📒 Mijoz hisobi` barcha kirim va xarajatlarni, jami olingan va ishlatilgan pulni ko'rsatadi.

`Dollar + Karta` kirimining ikkala qismi karta summasi kiritilgach birga saqlanadi.
O'rtada bekor qilinsa, pul yozilmaydi; mijozning nomi saqlanadi. Hozircha pul
olinmagan bo'lsa ham `/cancel` bilan mijoz oynasiga o'tishingiz mumkin.
Keyingi safar mijozni ro'yxatdan tanlang. Yana kirim qo'shish uchun uning oynasida
`💰 Mijozdan pul oldim`ni bosing — shu to'rtta variant yana chiqadi.

Mijoz hisobidagi so'm (naqd va karta birga) va dollar alohida yuritiladi.
Pul umumiy kassada yuritiladi: undan istalgan mijozga yoki xodimga sarflash mumkin.
Mijozdan hali pul olinmagan bo'lsa ham unga xarajat yoziladi. Mijoz uchun alohida
qoldiq yoki minus hisoblanmaydi; faqat undan olingan va unga ishlatilgan pul ko'rsatiladi.
Dollar avtomatik ravishda so'mga aylantirilmaydi.
Har bir operatsiya umumiy naqd, dollar yoki karta qoldig'iga ham bir marta ta'sir qiladi.
Har qanday xarajat uchun tanlangan umumiy hisobda (naqd so'm, dollar yoki karta) yetarli pul bo'lishi kerak. Balans yetmasa xarajat saqlanmaydi va hisobot yuborilmaydi.

Yozuv saqlangach mijoz oynasi ochiq qoladi. `/cancel` joriy kiritishni bekor qilib,
shu mijozga qaytaradi. Boshqa mijozga o'tish uchun `👥 Mijozlar`ni, umumiy hisobga
qaytish uchun `⬅️ Asosiy menyu`ni bosing. Oddiy `💰 Pul oldim` tugmasi umumiy kirim uchun.

Mijoz nomi 80 belgigacha bo'lishi mumkin. Katta-kichik harf va ortiqcha bo'shliqlar
bilan farqlanadigan nom qayta qo'shilsa, mavjud hisob ochiladi. Ismi bir xil ikki
mijoz uchun familiya yoki boshqa farqlovchi izohni nomga qo'shing.
Ro'yxat uzun bo'lsa, keyingi va oldingi sahifa tugmalari chiqadi.
Mijozlar va ularning yozuvlari bazada saqlanadi; bot qayta ishga tushganda mijozni qayta tanlang.

## Boshqa xarajatlar

`🧾 Boshqa xarajatlar` oynasida `Ijara 200000` yoki `Transport 20$` deb yozing.
Kartadan to'lov uchun `💳 Boshqa xarajat kartadan` tugmasini bosing.
Bu yozuvlar hech bir mijozga biriktirilmaydi, umumiy kassadan ayiriladi.
`📒 Boshqa xarajatlar hisobi` mijozga biriktirilmagan barcha xarajatlarni va jami
sarflangan so'm hamda dollarni ko'rsatadi. Xodimga biriktirilgan to'lovlar bu ro'yxatga
kirmaydi. Eski mijozsiz xarajatlar ham shu ro'yxatda qoladi.
Asosiy menyuda avvalgidek to'g'ridan-to'g'ri yozilgan xarajatlar ham mijozsiz saqlanadi.

## Dollar xarajatlari

Asosiy menyuda xarajat nomi va summani yozib, oxiriga `$` belgisini qo'ying:

- `Furnituraga 300$` — dollar qoldig'idan $300 ayiriladi.
- `Usta 12.50$` yoki `Usta 12,50 $` — dollar qoldig'idan $12.50 ayiriladi.

Summani musbat va ko'pi bilan ikki kasr xonasi bilan kiriting. Xarajat dollar sifatida
tarix, statistika va qabul qiluvchiga yuboriladigan xabarda ham ko'rsatiladi.
`$` belgisisiz xarajatlar so'mda hisoblanadi. `💳 Kartadan` bo'limi so'mda yuritiladi;
dollar xarajatini kiritish uchun `/cancel` bilan asosiy menyuga qayting.

## Karta hisobi

Karta hisobi so'mda yuritiladi. O'tkazmani bank ilovangizda bajarasiz, keyin botga yozasiz.

1. `💰 Pul oldim` → `💳 Karta` → `500000`: karta qoldig'iga 500 000 so'm qo'shiladi.
2. `💳 Kartadan` → `Ali 200000`: 1% komissiya bilan karta qoldig'idan 202 000 so'm ayiriladi.
3. Karta qoldig'i 298 000 so'm bo'ladi; naqd so'm va dollar qoldiqlari o'zgarmaydi.

Kartadagi mablag' yetarli bo'lmasa, xarajat yozilmaydi. Har bir karta xarajati uchun
`💳 Kartadan` tugmasini bosing. Saqlangandan keyin bot asosiy menyuga qaytadi.
Hisobotni oladigan odamga har bir kirim va xarajat alohida yuboriladi.
Xabarda hisob turi (naqd so'm, dollar yoki karta), summa, vaqt, kirimda kimdan olingani
(kiritilgan bo'lsa) va xarajatda izohi ko'rsatiladi.
Mijoz oynasidan yozilgan kirim va xarajat xabarida mijozning nomi ham chiqadi.
Qoldiqlar, statistika, tarix, dollar maydalash va reset haqidagi xabarlar unga yuborilmaydi.
Kassa amallarini faqat `CASHIER_ID` dagi kassir bajaradi.
Boshliq xodimlar, mijozlar, balans va statistikani tugmalar yoki
`/xodimlar`, `/mijozlar`, `/hisob`, `/statistika` orqali ko'ra oladi.

Qabul qiluvchini almashtirish uchun serverdagi `.env` faylida `REPORT_CHAT_ID` ni yangilab,
botni qayta ishga tushiring. Yangi qabul qiluvchi botga `/start` yuborgan bo'lishi kerak.
Xabar yetib bormasa, operatsiya bazada saqlanadi va kassirga bu haqda bildiriladi.

## Statistika

Avval `Bugun`, `Shu oy` yoki `Barcha vaqt` davrini tanlang. Hisobotda faqat:

- Tanlangan davrdagi barcha xarajatlar: izoh, summa, naqd yoki karta hisobi va vaqt.
- Shu davrda jami sarflangan so'm (naqd va karta birga) va dollar alohida.
- Hozirgi naqd so'm, karta va dollar qoldiqlari.

Har bir xarajat alohida satrda chiqadi, bir xil nomdagilari ham alohida saqlanadi.
Ro'yxat vaqt bo'yicha tartiblanadi; uzun bo'lsa, to'liq holda bir nechta xabarga bo'linadi.
`Bugun` va `Shu oy` Toshkent vaqti bo'yicha joriy kun va kalendar oyni bildiradi.
`Barcha vaqt` mavjud bazadagi barcha xarajatlarni qamrab oladi.
Qoldiqlar tanlangan davrdan qat'i nazar hozirgi hisobni ko'rsatadi.
Dollar maydalash xarajatlar ro'yxati va jami sarfga qo'shilmaydi, qoldiqlarda hisobga olinadi.

## Alohida ishga tushirish

Ushbu nusxani alohida papkada ishga tushiring. `.env` ichida yangi botning
`BOT_TOKEN`, `CASHIER_ID` va `REPORT_CHAT_ID` qiymatlarini belgilang.
Eski ishlayotgan botning tokenidan foydalanmang: har bir bot uchun alohida token kerak.

`kassa.db` birinchi ishga tushirishda shu loyiha papkasida yangidan yaratiladi.
Mijozlar, xodimlar va operatsiyalar bo‘sh boshlanadi. Zaxira nusxalari ham
shu papkadagi `backups/` ichida saqlanadi.

## Tekshirish

```sh
.venv/bin/python -m unittest -v test_kassa.py test_clients.py test_employees.py test_commission.py test_undo.py
```

Testlar vaqtinchalik bazadan foydalanadi; Telegramga haqiqiy xabar yubormaydi.

Mijozni ro'yxatdan olib tashlash uchun uning oynasida
`🗑 Mijozni o'chirish` → `✅ Ha, o'chirish` tugmalarini bosing.
Buni faqat kassir bajaradi. Mijoz ikkala odamning ro'yxatidan yashiriladi;
kirim-xarajatlar, statistika va umumiy balans saqlanadi.
Shu ism bilan mijoz qayta qo'shilsa, oldingi hisobi bilan ro'yxatga qaytadi.

Umumiy «Pul oldim»da hisob turini tanlab, kimdan olinganini va keyingi xabarda summani yozish mumkin. Ism va summa bitta xabarda ham qabul qilinadi.

## Tranzaksiyani qaytarish

Asosiy menyudagi `↩️ Tranzaksiyani qaytarish` yoki `/qaytarish` orqali
yozuvni tanlang va `✅ Qaytarish` bilan tasdiqlang. Ro'yxat sahifalanadi.
Faqat kassir qaytara oladi. Tasdiqlashdan oldin bekor qilish mumkin.

Xarajat qaytarilganda pul tegishli balansga qaytadi; kirim qaytarilganda
undan ayriladi. Natija mijoz/xodim hisobi, tarix va statistikada ham aks etadi.
Qaytarish balansni manfiy qilsa, bajarilmaydi. Dollar maydalashning ikkala
yozuvi birga qaytariladi; dollar+karta kirimining har bir yozuvi alohida tanlanadi.
Asl yozuvlar va xodimga bog'lanish ma'lumoti `transaction_undo` jadvalida saqlanadi.

`🧾 Boshqa xarajatlar` → `💵 Boshqa dollar xarajat` orqali xarajat nomi
va dollar miqdorini yozing. Bu rejimda `$` belgisi shart emas.

Kartadan barcha xarajatlarga, jumladan mijoz va xodim to'lovlariga 1% komissiya
qo'shiladi. Tasdiq, boshliqqa xabar, statistika va mijoz/xodim hisobida jami
summa ko'rinadi. Komissiya bilan jami mablag' yetmasa xarajat yozilmaydi.
Kasrli komissiya keyingi butun so'mga yaxlitlanadi. Tranzaksiyani qaytarishda
komissiya bilan jami pul qaytadi. Eski yozuvlar qayta hisoblanmaydi.
