# Google_ChatGPT_learning — аналітика заявок меблевої студії

## Українська

Цей репозиторій містить невелику систему на Python для обробки трьох різноформатних таблиць заявок менеджерів меблевої студії. Вона зводить їх до спільного формату, формує звіти та автономний HTML-дашборд. Звітна дата для поточного набору даних — 02.11.2026.

Проєкт спирається на навчальну вправу **«Збірка ШІ-агента за 90 хвилин»** як на освітню відправну точку. Поточна система є подальшою самостійною розробкою: її реалізація, додаткові правила, обробка даних, звітність, dashboard, тести та інструкції були розвинуті для цього репозиторію. Це не твердження про незалежне походження кожної початкової ідеї; матеріали вебінару не є власністю цього проєкту.

### Можливості

- Читає три CSV з різними назвами полів і форматами дат, сум та етапів, нормалізує записи й об'єднує їх.
- Відрізняє точні копії рядків у межах таблиці менеджера від окремих заявок того самого клієнта в різних менеджерів. Спільного клієнта визначає за телефоном.
- Позначає пропуски та інші проблеми якості даних; відсутні значення не підмінює нулями.
- Виявляє прострочені наступні кроки лише для заявок із непорожньою відкритою стадією, ранжує подальший контакт і окремо показує кроки на дату звіту.
- Створює зведений та персональні звіти менеджерів, а також чернетки повідомлень для пріоритетних контактів. Нічого не надсилає.
- Зберігає незмінну історію версій звіту: однаковий вміст повторно не архівується, змінений отримує наступний вільний номер версії.
- Генерує відтворювані демонстраційні таблиці та будує автономний адаптивний HTML-дашборд з графіками, фільтрами менеджерів, світлою/темною темою й перевірками якості даних. Dashboard не використовує CDN або мережеві запити.
- Містить автоматизований набір із 41 тесту та інструкції для проєктних ролей.

### Демонстраційні дані й безпека

Файли `data/zayavky_*.csv`, звіти та dashboard у репозиторії побудовані лише на штучних демонстраційних даних. Імена, телефони, дати й суми вигадані; телефонний код `+380 00` не є чинним операторським кодом. Це не дані реальних клієнтів.

Не додавайте до відкритого Git-репозиторію реальні імена, телефони, заявки, суми, коментарі, повідомлення чи інші персональні/клієнтські дані. Для реальної роботи використовуйте окремі локальні каталоги `data/private/`, `reports/private/`, `history/private/` і `dashboard/private/`; вони виключені через `.gitignore`. Перед будь-якою публікацією перевірте `git status` і вміст файлів. Скрипти працюють локально; жодні повідомлення автоматично не надсилаються.

### Вимоги

- Python 3.10 або новіший; достатньо стандартної бібліотеки Python.
- Додаткові Python-пакети встановлювати не потрібно.
- Git потрібен лише для клонування та керування копією репозиторію.

### Встановлення і запуск

```bash
git clone https://github.com/<власник>/<репозиторій>.git
cd Google_ChatGPT_learning

# Тести
python3 -B -m unittest discover -s tools -p "test_*.py" -v

# Сформувати/оновити звіти; історія додається лише коли вміст змінився
python3 tools/zvit.py

# Побудувати dashboard з актуальних зведеної таблиці та звіту
python3 tools/build_dashboard.py
```

Відкрийте `dashboard/dashboard.html` локально у браузері. Вебсервер не потрібен. Для альтернативних шляхів до вхідних чи вихідних файлів дивіться параметри `--help` відповідного скрипту.

Демонстраційні CSV вже включені. Скрипт спершу дозволяє перевірити специфікацію без запису. Перегенерація за замовчуванням використовує seed `20261102`; прапорець `--force` потрібен, щоб замінити наявні CSV:

```bash
python3 tools/generate_demo_data.py --dry-run
python3 tools/generate_demo_data.py --seed 20261102 --force
python3 tools/generate_demo_data.py --seed 42 --out /шлях/до/окремої/папки
```

Не використовуйте `--force` для директорій з потрібними вам файлами: генератор перезаписує CSV з такими самими іменами.

### Результати

| Шлях | Призначення |
|---|---|
| `reports/zvedena.csv` | Усі рядки джерел із позначками дублів, заявок тижня, прострочення, кроків на сьогодні та проблем даних |
| `reports/zvit.md` | Загальний стислий звіт |
| `reports/managers.md` | Розрахунки та висновки окремо по кожному менеджеру |
| `reports/chernetky.md` | Чернетки подальших повідомлень; відправлення не виконується |
| `history/zvit-<дата>.md` | Архівна версія звіту; змінені версії отримують суфікси `-2`, `-3` тощо |
| `dashboard/dashboard.html` | Окремий HTML-dashboard, зібраний з `reports/zvedena.csv` і `reports/zvit.md` |

`reports/` і dashboard перегенеровуються запуском скриптів. Наявні файли `history/` не перезаписуються та не видаляються. Якщо зведення і звіт містять несумісні дані, dashboard показує попередження.

### Правила підрахунку та обмеження

- Заявка — запис у таблиці менеджера; клієнт визначається номером телефону. Різні заявки одного клієнта у різних менеджерів рахуються окремо.
- Дублем є лише повний збіг усіх значень рядка після читання CSV у тій самій таблиці. Технічні лапки CSV та закінчення рядків не мають значення.
- «Забута» заявка має дату наступного кроку раніше за дату звіту та непорожню відкриту стадію. Заявки з невідомою або закритою стадією не включаються.
- «Крок на сьогодні» відображається окремо і не є простроченим контактом.
- У джерельних таблицях немає історії переходів між стадіями та дати підписання договору. Тому поточна стадія — операційний критерій, а кількість договорів за заявками тижня не є кількістю договорів, підписаних саме того тижня.
- Суми й інші пропуски залишаються невідомими, а не нульовими. Демонстраційні результати не є прогнозом чи оцінкою реальної діяльності.

### Структура репозиторію

```text
.
├── AGENTS.md       правила роботи агентів у проєкті
├── CLAUDE.md       додаткові інструкції для Claude Code
├── README.md       документація українською та англійською
├── brief.md        визначення, погоджені вимоги та поточний стан
├── agents/         інструкції для ролей звітника, перевірника й керівника
├── data/           три синтетичні CSV-таблиці
├── tools/          генератор, обробка звітів, dashboard builder і тести
├── reports/        актуальні згенеровані звіти
├── history/        архів звітів
└── dashboard/      згенерований автономний HTML
```

Файли в `agents/` описують задачі та критерії роботи; це не фонові автономні процеси.

### Походження та ролі

Освітня основа — **«Збірка ШІ-агента за 90 хвилин»**. Вона дала навчальний контекст і початкову рамку; реалізація та перелічені вище розширення належать до подальшої роботи над цим проєктом. Внески інструментів описуються відповідно до їх фактичної ролі:

- **Власник проєкту:** ініціював проєкт, є автором вимог, ухвалює рішення та затверджує результати.
- **ChatGPT:** координував і проєктував роботу, допомагав уточнювати вимоги, структуру, задачі та критерії приймання.
- **Claude Code CLI:** основний інструмент розробки, яким реалізовано головну функціональність проєкту.
- **Codex CLI:** інструмент незалежної перевірки та додаткової розробки.

Ці ролі описують процес роботи, а не авторство всіх початкових ідей. Матеріали вебінару не включені до репозиторію і не оголошуються власністю проєкту.

### Ліцензія

Ліцензія MIT поширюється на компоненти проєкту, розроблені самостійно. Навчальні матеріали вебінару та інші сторонні матеріали не є власністю правовласника й не охоплюються цією ліцензією.

### Контакт

Для запитань і зворотного зв'язку: `findepo@ukr.net`.

---

## English

This repository contains a small Python system for processing three differently formatted lead tables from a furniture studio's managers. It normalizes and combines the records, produces reports, and builds a standalone HTML dashboard. The current dataset uses a report date of 2 November 2026.

The project takes the educational exercise **“Збірка ШІ-агента за 90 хвилин”** (“Building an AI Agent in 90 Minutes”) as its learning starting point. The system in this repository is subsequent independent development: its implementation, added rules, data handling, reporting, dashboard, tests, and instructions were developed for this project. This does not claim that every underlying idea originated independently; the webinar materials are not owned by this project.

### Features

- Reads three CSV files with different field names and date, amount, and stage formats, normalizes the records, and combines them.
- Distinguishes exact duplicate rows within one manager's table from separate applications by the same client across managers. A shared client is identified by phone number.
- Flags missing values and other data quality issues; missing values are not replaced with zero.
- Detects overdue next steps only for applications with a non-empty open stage, prioritizes follow-up, and reports steps due on the report date separately.
- Produces a consolidated report, manager-specific reports, and draft messages for priority follow-ups. It sends nothing.
- Keeps report history immutable: identical content is not archived again, while changed content receives the next available version number.
- Generates reproducible synthetic datasets and builds a standalone, responsive HTML dashboard with charts, manager filters, light/dark themes, and data quality checks. The dashboard uses no CDN or network requests.
- Includes an automated suite of 41 tests and project role instructions.

### Demo data and data safety

The `data/zayavky_*.csv` files, reports, and dashboard in this repository use synthetic demo data only. Names, phone numbers, dates, and amounts are fictional; the `+380 00` phone code is not a valid operator code. These are not real client records.

Do not add real names, phone numbers, applications, amounts, comments, messages, or other personal/client data to a public Git repository. For real work, use separate local directories `data/private/`, `reports/private/`, `history/private/`, and `dashboard/private/`; `.gitignore` excludes them. Check `git status` and file contents before any publication. The scripts run locally; no messages are sent automatically.

### Requirements

- Python 3.10 or newer; the Python standard library is sufficient.
- No additional Python packages need to be installed.
- Git is needed only to clone and manage a repository copy.

### Setup and usage

```bash
git clone https://github.com/<owner>/<repository>.git
cd Google_ChatGPT_learning

# Run the test suite
python3 -B -m unittest discover -s tools -p "test_*.py" -v

# Build/update reports; history is added only when content changes
python3 tools/zvit.py

# Build the dashboard from the current consolidated table and report
python3 tools/build_dashboard.py
```

Open `dashboard/dashboard.html` locally in a browser. No web server is required. For alternate input or output paths, see `--help` for the relevant script.

Demo CSV files are included. You can first validate the data specification without writing files. The generator defaults to seed `20261102`; `--force` is required to replace existing CSV files:

```bash
python3 tools/generate_demo_data.py --dry-run
python3 tools/generate_demo_data.py --seed 20261102 --force
python3 tools/generate_demo_data.py --seed 42 --out /path/to/a/separate/folder
```

Do not use `--force` in a directory containing files you need to keep: the generator replaces CSV files with matching names.

### Outputs

| Path | Purpose |
|---|---|
| `reports/zvedena.csv` | All source rows with duplicate, weekly-application, overdue, due-today, and data-issue markers |
| `reports/zvit.md` | Concise overall report |
| `reports/managers.md` | Calculations and findings for each manager |
| `reports/chernetky.md` | Draft follow-up messages; no messages are sent |
| `history/zvit-<date>.md` | Archived report version; changed versions receive `-2`, `-3`, and later suffixes |
| `dashboard/dashboard.html` | Standalone HTML dashboard built from `reports/zvedena.csv` and `reports/zvit.md` |

Running the scripts regenerates `reports/` and the dashboard. Existing files in `history/` are never overwritten or deleted. If the consolidated data and report disagree, the dashboard displays a warning.

### Counting rules and limitations

- An application is a record in a manager's table; a client is identified by phone number. Separate applications for one client across managers are counted separately.
- A duplicate is a complete match of every field value after CSV parsing, within the same table. CSV quoting and line endings do not affect the match.
- An “overdue” application has a next-step date earlier than the report date and a non-empty open stage. Applications with an unknown or closed stage are excluded.
- A step due on the report date is shown separately and is not overdue.
- The source tables do not contain stage-transition history or contract signing dates. The current stage is therefore an operational criterion, and contracts among applications created during the week are not necessarily contracts signed during that week.
- Missing amounts and other missing values remain unknown rather than being treated as zero. Demo results are not a forecast or assessment of real business activity.

### Repository structure

```text
.
├── AGENTS.md       project agent working rules
├── CLAUDE.md       additional instructions for Claude Code
├── README.md       documentation in Ukrainian and English
├── brief.md        definitions, agreed requirements, and current state
├── agents/         instructions for reporting, review, and management roles
├── data/           three synthetic CSV tables
├── tools/          generator, report processor, dashboard builder, and tests
├── reports/        current generated reports
├── history/        report archive
└── dashboard/      generated standalone HTML
```

Files in `agents/` describe tasks and acceptance criteria; they are not background autonomous processes.

### Origin and roles

The educational basis is **“Збірка ШІ-агента за 90 хвилин”** (“Building an AI Agent in 90 Minutes”). It provided the learning context and initial framework; the implementation and extensions listed above were developed afterward for this project. Tool contributions are described according to their actual roles:

- **Project owner:** initiated the project, authored its requirements, makes decisions, and approves results.
- **ChatGPT:** coordinated and architected the work, helping define requirements, structure, tasks, and acceptance criteria.
- **Claude Code CLI:** the primary development tool used to implement the main project functionality.
- **Codex CLI:** a tool for independent review and additional development.

These roles describe the workflow; they do not claim that every initial idea was original. Webinar materials are not included in the repository and are not claimed as project property.

### License

The MIT License applies to components independently developed for this project. The educational webinar materials and other third-party materials are not the copyright holder's property and are not covered by this license.

### Contact

For questions and feedback: `findepo@ukr.net`.
