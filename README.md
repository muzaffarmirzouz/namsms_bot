# SMS Tanishuv: Telegram bot + OBS overlay

Tomoshabin botga e'lon yozadi. Oddiy xabar darhol OBS efirida chiqadi, shubhalisi admin tekshiruviga boradi.

## Fayllar

- `main.py`: bot va veb-server (bitta jarayonda ishlaydi)
- `overlay.html`: OBS uchun efir sahifasi (yugurib o'tuvchi qator va kartochka)
- `requirements.txt`, `Procfile`: Railway uchun

## 1. Bot yaratish

1. @BotFather → `/newbot` → tokenni oling.
2. O'z Telegram ID'ingizni @userinfobot orqali bilib oling.

## 2. Railway'ga joylash

1. Fayllarni yangi GitHub repoga yuklang.
2. Railway → New Project → Deploy from GitHub → shu repo.
3. **Variables** bo'limiga qo'shing:

| O'zgaruvchi | Misol | Izoh |
|---|---|---|
| `BOT_TOKEN` | `123456:ABC...` | BotFather bergan token |
| `ADMIN_IDS` | `111111,222222` | Tasdiqlaydigan adminlar ID'lari |
| `BOT_SHOW` | `@NamSMS_bot` | Efirda ko'rinadigan bot nomi |
| `DB_PATH` | `/data/data.db` | Baza fayli (pastdagi Volume bilan) |
| `COOLDOWN_MIN` | `5` | Bir odam necha daqiqada 1 ta e'lon yubora oladi |
| `REQUIRED_CHANNEL` | `@Namanganliklar_uz` | Majburiy a'zolik kanali (bo'sh qoldirilsa tekshirilmaydi) |
| `MSG_TTL_MIN` | `10` | Tomoshabin xabari efirda necha daqiqa aylanadi, keyin o'zi o'chadi |
| `MAX_LEN` | `150` | E'lon matni uzunligi |
| `AUTO_MODE` | `1` | `1` = oddiy xabarlar avtomat efirga, `0` = hammasini admin tasdiqlaydi (botda `/avto` bilan ham o'zgaradi) |
| `CITY_NAME` | `Namangan` | Ob-havo shahri nomi (efirda shunday yoziladi) |
| `CITY_LAT`, `CITY_LON` | `40.9983`, `71.6726` | Shahar koordinatalari (standart Namangan) |
| `AD_TTL_SEC` | `60` | Admin reklamasi efirda necha soniya turadi |

4. **Volume** qo'shing: Service → Settings → Volumes → mount path `/data`.
   Volume bo'lmasa, har deploy'da baza o'chib ketadi.
5. Settings → Networking → **Generate Domain**. Masalan:
   `https://sms-tanishuv-production.up.railway.app`

## 3. OBS'ga qo'shish

1. Sources → **+** → **Browser**.
2. URL: `https://SIZNING-DOMEN.up.railway.app/overlay`
3. Width: `1920`, Height: `1080`.
4. OK. Fon shaffof, faqat yozuvlar ko'rinadi.

URL oxiriga qo'shimcha sozlamalar qo'shish mumkin:

- `?speed=100`: qator tezligi (standart 140)
- `?card=10`: kartochka necha soniya turadi (standart 8)
- `?scale=1.2`: hamma narsani yana kattalashtirish (1.2 = 20% katta, 0.8 = kichikroq). Standart o'lcham telefonda ko'rishga moslangan
- `?adevery=3`: qatorda har nechta xabardan keyin reklama qo'yilsin (standart 2)
- `?adlabel=E'LON`: reklama belgisidagi yozuv (standart REKLAMA)
- `?pinevery=3`: admin e'loni har nechta xabardan keyin chiqsin (standart 2)
- `?pinlabel=NAM TV`: admin e'loni belgisidagi yozuv (standart ADMIN)
- `?label1=SMS CHAT`: chapdagi katta yozuv (standart "SMS CHAT")
- `?label2=Xabar yuboring`: almashganda chiqadigan 1-qator (2-qator bot nomi, `BOT_SHOW` dan)
- `?labelsec=5`: chapdagi yozuv necha soniyada almashsin (standart 5)

Masalan: `.../overlay?speed=100&card=10`

## Valyuta kursi va ob-havo

Server har soat boshida (14:00, 15:00...) o'zi yangilaydi va yangilangan holatini efirga beradi:
- **KURS**: Markaziy bank (cbu.uz) rasmiy kursi: Dollar, Yevro, Rubl va kunlik o'zgarish (▲/▼).
- **OB-HAVO**: Open-Meteo: hozirgi harorat, osmon holati, bugungi eng past va eng baland harorat.

Har soat boshida "Soat 15:00 holatiga" degan yashil kartochka 15 soniya chiqadi (kurs va ob-havo birga).
Botda `/malumot` yozsangiz, hozirning o'zida yangilab efirga chiqaradi.

Shuningdek, ular pastki qatorda doim yashil belgi bilan, har 3 ta xabardan keyin chiqadi. Xabar bo'lmasa, qatorda
faqat kurs va ob-havo aylanadi. Sayt vaqtincha ishlamasa, oxirgi ma'lumot qoladi.

OBS linki sozlamalari:
- `?infoevery=5`: har nechta xabardan keyin chiqsin (standart 3)
- `?kurs=0`: kursni o'chirish
- `?havo=0`: ob-havoni o'chirish
- `?infocard=20`: soatlik kartochka necha soniya tursin (standart 15)

## Bot qanday ishlaydi

**Tomoshabin:**
1. `/start` → @Namanganliklar_uz kanaliga a'zolik tekshiriladi (a'zo bo'lmasa, kanal tugmasi chiqadi).
2. "18 yoshdan kattamanmi?" tasdig'i.
3. Ism (yosh va shahar ixtiyoriy, yosh yozilsa 18+ bo'lishi shart) → xabar matni.
4. "Telefon raqamingiz efirda chiqsinmi?" — xohlasa, raqamini Telegram'ning
   "Raqamimni yuborish" tugmasi orqali tasdiqlaydi (faqat o'z raqami qabul qilinadi, qo'lda yozib bo'lmaydi).
   Tasdiqlangan raqam saqlanadi, keyingi safar bir bosishda tanlanadi.
5. Xabar efirga chiqadi (ekranda raqamsiz, #1/#2 belgilarisiz) va 10 daqiqadan keyin o'chadi.

**Admin:**
- Admin `/` bosganda barcha buyruqlar menyuda chiqadi (oddiy foydalanuvchiga faqat /start va /help). `/admin` hammasini ro'yxat qilib ko'rsatadi.
- Oddiy xabarlar avtomat efirga chiqadi. Sizga **ovozsiz** xabar keladi (telefon jiringlamaydi),
  tagida **Efirdan olish** va **Olish va bloklash** tugmalari bor.
- Shubhali xabar (pul, reklama, kanal, raqam, katta harf va h.k.) efirga chiqmaydi, sizga
  **ovozli** keladi: **Efirga** / **Rad etish** / **Rad etish va bloklash**.
- So'kinish, havola va telefon raqam darhol rad etiladi, sizgacha ham kelmaydi.
- `/avto`: avtomat rejimni yoqish/o'chirish
- `/taqiq so'z`: so'kinish ro'yxatiga so'z qo'shish
- `/shubha so'z`: shubhali ro'yxatga so'z qo'shish
- `/ochir so'z`: siz qo'shgan so'zni olib tashlash
- `/sozlar`: siz qo'shgan so'zlar va rejim holati
- `/malumot`: kurs va ob-havoni hozir yangilab efirga chiqarish
- `/stat`: statistika
- `/tozala`: efirdagi qatorni tozalash (masalan, yangi ko'rsatuv boshida)
- `/elon Matn`: pastki qatorga doimiy admin e'loni (binafsha fon, ADMIN belgisi). Ekranda kartochka bo'lib chiqmaydi, o'chirmaguningizcha aylanadi
- `/elonlar`: doimiy e'lonlar ro'yxati, har birida "O'chirish" tugmasi
- `/reklama Matn`: reklamani efirga chiqarish
- `/reklamalar`: oxirgi 10 ta reklama, har birida "Yana chiqarish" va "Hozir o'chirish" tugmalari

Reklama har yozilganda 1 daqiqa (`AD_TTL_SEC`) turadi va o'zi o'chadi. U ikki joyda chiqadi:
yuqori chapdagi alohida ko'k kartochkada (pastida qolgan vaqtni ko'rsatuvchi chiziq bor) va
pastki yugurib o'tuvchi qatorda xabarlar orasida. Ikkalasida ham boshqa rang va shriftda,
"REKLAMA" belgisi bilan, ismsiz chiqadi. Tomoshabin xabari kartochkasi pastki chapda,
shuning uchun ular bir-birini to'smaydi.

## Himoya

- Xabar ichiga yozilgan telefon raqam, havola va @username bloklanadi. Raqam faqat Telegram
  orqali tasdiqlangan bo'lsa va egasi xohlasa, alohida yashil belgi bilan chiqadi.
- Botdan foydalanish uchun `REQUIRED_CHANNEL` (standart @Namanganliklar_uz) kanaliga a'zo bo'lish shart.
  **Muhim:** bot o'sha kanalga admin qilib qo'shilgan bo'lishi kerak, aks holda a'zolikni tekshira olmaydi
  (bunda tekshiruv o'tkazib yuboriladi va Railway logida `[sub]` xatosi chiqadi).
- 18 yoshdan kichiklar e'lon bera olmaydi.
- Bir odam `COOLDOWN_MIN` daqiqada faqat 1 ta e'lon yubora oladi.
- So'kinish filtri o'zbek (lotin va kirill) va rus tilidagi so'zlarni, "suuuka" kabi cho'zib yozilganlarini ham ushlaydi.
