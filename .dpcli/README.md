# dpcli — журнал, карточки задач и приёмка

Утилита процесса «главная сессия ↔ координатор модуля ↔ исполнители ↔ ревьюер» для проектов, где работают агенты Claude Code. Хранит журнал модулей (карточки задач, отчёты, события, решения, вопросы пользователю), ведёт ветки и рабочие копии (git worktree), прогоняет проверки приёмки и сливает ветки. Вывод короткий; подробности — `--full`.

Коды выхода: 0 — ок, 1 — ошибка или FAIL, 2 — неверные аргументы. Ошибка — одна строка `dpcli: …`.

## Требования

- python3 ≥ 3.10 (только стандартная библиотека; PyYAML не обязателен — есть встроенный разбор подмножества YAML);
- git;
- опционально: tmux (окна для `job`/`lock`/`accept --bg`); Ollama с моделью `bge-m3` нужна только для смыслового поиска (`search --sem`, `index`) и по умолчанию не используется.

## Установка

1. Скопировать каталог `.dpcli` в корень git-проекта.
2. Выполнить `.dpcli/dpcli init`.

`init` создаёт (всё идемпотентно):

| Что | Где |
|---|---|
| Конфиг из примера (если конфига нет) | `dpcli.yml` |
| Агенты с подставленными плейсхолдерами | `.claude/agents/*.md` |
| Скиллы | `.claude/skills/<имя>/SKILL.md` |
| Описание процесса | `.claude/dpcli-workflow.md` |
| Блок между маркерами `<!-- dpcli:begin -->` … `<!-- dpcli:end -->` | `CLAUDE.md` |
| Разрешение `Bash(.dpcli/dpcli *)` | `.claude/settings.json` |
| Строки `.read_*`, `build/dpcli/` | `.gitignore` |

Режимы `init`:

- повторный запуск безопасен: ничего не меняется, если результат уже актуален; что записал `init`, учтено в `.claude/.dpcli-manifest.json`; такие файлы, изменённые вручную, без `--force` не перезаписываются — выводится сообщение;
- файлы проекта (нет в манифесте) `init` не перезаписывает и не удаляет никогда, даже с `--force`: если в `.claude/agents` уже есть агент с именем агента dpcli — агент dpcli пропускается («пропущен — агент проекта; роль: см. roles в конфиге»); так же скилл с тем же именем и файл процесса. `CLAUDE.md` и `settings.json` — точечные вставки (блок между маркерами, одно разрешение);
- `--force` — перезаписать/удалить изменённые вручную файлы из манифеста;
- `--check` — только проверить, актуально ли настроено (ничего не пишет);
- `--dry-run` — показать, что было бы сделано;
- `--json` | `--yaml` — формат конфига, если он создаётся (по умолчанию `dpcli.yml`).

Точные флаги: `.dpcli/dpcli init -h`.

После `init` закоммитить результат (коммиты делает только главная сессия).

## Конфиг

`dpcli.json` или `dpcli.yml`/`dpcli.yaml` в корне проекта (ищется вверх от текущего каталога до корня git; при обоих json приоритетнее). Все ключи необязательны. Полный список с комментариями и умолчаниями — [`dpcli.example.yml`](dpcli.example.yml). Кратко:

- `project`, `main_branch`, `module_branch` (`feature/{module}`), `task_branch` (`{module}/{task}`);
- `copies_dir`, `module_copy`, `task_copy` — где создаются рабочие копии (подстановки `{project}`, `{module}`, `{task}`, `{copies}`);
- `plan_dir` (`docs/plan`), `contracts_dir` (`docs/contracts`), `docs_dir` (`docs`);
- `checks.env`, `checks.tests` (шаблон команды для проверок `{tests: …}`, `{filter}`), `checks.log_dir` (`build/dpcli`);
- `artifacts_dir`, `reserved_codes`, `gc.ignore_dirs`, `gc.ignore_globs`;
- `sem` (`enabled: false` по умолчанию, `model`, `url`, `cache_dir`, `globs`), `jobs` (`dir`, `tmux_session`, `cpu_slots`), `locks`;
- `agents_dir` (`.dpcli/agents`), `workflow` (`.claude/dpcli-workflow.md`);
- `roles` — роли своих агентов проекта: `{имя: {role: coordinator|executor|reviewer|status, review: bool}}`; реестр агентов = `agents_dir` + `.claude/agents` с `dpcli_role` во frontmatter + `roles` (перекрывает); смотреть — `dpcli agents`;
- `docs` (`extra`, `exclude`, `types`, `statuses`, `max_kb`, `max_kb_mode`, `summary_max`, `registries`).

## Агенты

Определения dpcli — `.dpcli/agents/*.md`: формат агента Claude Code (frontmatter `name, description, model, effort, tools/disallowedTools, skills`) плюс ключи dpcli:

- `dpcli_role`: `coordinator` | `executor` | `reviewer` | `status`;
- `dpcli_review`: `true` | `false` — нужен ли ревьюер после PASS приёмки (для исполнителей).

Поставляются: `dp-coordinator` (opus), `dp-engineer`, `dp-researcher`, `dp-writer` (sonnet), `dp-mechanic` (haiku), `dp-reviewer` (opus), `dp-status` (haiku). Тексты агентов короткие; общие правила — только в описании процесса, агенты на него ссылаются.

Плейсхолдеры `{{cli}}`, `{{workflow}}`, `{{plan_dir}}`, `{{contracts_dir}}`, `{{docs_dir}}`, `{{main_branch}}`, `{{module_branch}}`, `{{project}}` подставляет `init` и кладёт результат в `.claude/agents/`. Агентов проекта `init` не трогает: одноимённый файл в `.claude/agents/` пропускается.

**Свои агенты в ролях процесса:** ключ `roles` в `dpcli.yml` (имя агента → `role`, `review`) или `dpcli_role`/`dpcli_review` во frontmatter. Тип исполнителя в `task new --type …` проверяется по этому реестру; посмотреть — `.dpcli/dpcli agents`.

```yaml
roles:
  my-designer: {role: executor, review: true}
```

**Модели.** Исполнители — sonnet (механика — haiku): с чёткой карточкой (цель, scope, dont_touch, проверки с порогами, контракты) этого достаточно. Opus — только если задача требует проектирования, которое нельзя вынести в план или контракт.

## Протокол сообщений

Агенты не пересказывают журнал, а передают ID и команду; детали читаются командами.

| От → кому | Сообщение |
|---|---|
| главная → координатор | `Модуль <м>: копия <путь>, ветка <ветка>. План: dpcli plan <м>. Новое: dpcli inbox <м>.` |
| координатор → исполнитель | вывод `task brief <ID>` как есть (особенности — в карточку через `task note`) |
| координатор → ревьюер | вывод `task brief <ID> --review` как есть |
| исполнитель → координатор | `<ID> reported` \| `<ID> blocked: <причина ≤15 слов>` \| `<ID> contract: <что поменять>` |
| ревьюер → координатор | `<ID> review accept` \| `<ID> review rework <n>` |
| координатор → главная | `<м>: <n> accepted, <n> в работе; шлюз Q<n>` или `<м> done` |
| главная → пользователь | свободно, по `status` / `digest` |

Решения пользователя попадают координатору через `decide` → `inbox`, а не пересказом. Не хватает сведений — вопрос одной строкой. Подробно — в описании процесса (`.claude/dpcli-workflow.md`, раздел «Протокол сообщений»).

## Флоу работы

1. **Главная сессия** (пользователь + Claude) создаёт модуль: `.dpcli/dpcli module new payments --code PY` — ветка, рабочая копия и журнал `<plan_dir>/payments/`. Пишет план (`<plan_dir>/payments/…`) и контракты.
2. Запускает **координатора** модуля (агент `dp-coordinator`) в копии модуля.
3. Координатор заводит задачи:
   ```
   .dpcli/dpcli task new payments --type dp-engineer --title "Округление суммы" \
     --goal "Сумма округляется до копеек" --plan-ref "PY-1" \
     --scope src/money.py --test rounding \
     --check no_todo "grep -c TODO src/money.py" "re:^0$"
   .dpcli/dpcli task show PY-1          # карточка; --full — полное задание исполнителю
   .dpcli/dpcli event PY-1 started --note "dp-engineer"
   ```
   `task new` сам создаёт рабочую копию и ветку задачи (`git worktree add -b <task_branch> <task_copy> <ветка модуля>`; есть — переиспользует; `--no-copy` — не создавать). Затем координатор запускает **исполнителя** с сообщением — выводом `.dpcli/dpcli task brief PY-1` как есть (одна задача, своя копия).
4. Исполнитель читает план по разделам, работает в своей копии, делает пробный прогон `accept PY-1 --dry` и сдаёт отчёт:
   ```
   .dpcli/dpcli plan payments PY-1
   .dpcli/dpcli report --template PY-1 > r.json   # заполнить
   .dpcli/dpcli report PY-1 < r.json
   ```
   Исполнитель коммитит свои файлы в ветке задачи (`git commit -- <пути>`); слияния веток — координатор и главная сессия (правила — `.claude/dpcli-workflow.md`).
5. Координатор принимает: `.dpcli/dpcli accept PY-1 -j 4`. FAIL — на доработку; PASS у типа с `dpcli_review: true` — состояние `checked` (ждёт ревью, `--no-review` — сразу принято), без ревью — `accepted`.
6. Ревью (свежий `dp-reviewer`): `.dpcli/dpcli review PY-1 --verdict rework --from - < review.json`; координатор смотрит `review PY-1 --show` и решает: `event PY-1 accepted --note "по ревью"` или доработка.
7. Слияние: ветка задачи → ветка модуля (в копии модуля), `.dpcli/dpcli event PY-1 merged --commit <хэш>`; свежее из основной ветки — `.dpcli/dpcli sync payments`; готовый модуль в основную: `.dpcli/dpcli merge feature/payments`.
8. Уборка: `.dpcli/dpcli gc` (список), `.dpcli/dpcli gc --remove`.

Наблюдение: `.dpcli/dpcli status`, `digest --since today`, `log payments`, `questions`.

## Команды

Справка по любой подкоманде — `.dpcli/dpcli <команда> -h`. Автор событий — `--by`, иначе `$DPCLI_ROLE`, иначе по ветке копии.

### Модули и ветки

```
.dpcli/dpcli module new <модуль> [--from main] [--code PY]   # ветка + копия + журнал, коммит в ветке
.dpcli/dpcli module init <модуль> [--plan П] [--contracts К] [--branch Б] [--copy К] [--code PY] [--legacy ПУТЬ]   # только журнал
.dpcli/dpcli sync <модуль|ветка> [-m М] [--trailer Т]          # влить основную ветку в ветку модуля (в её копии)
.dpcli/dpcli merge <ветка|модуль> [--into main] [--push] [--no-index] [-m М] [--trailer Т]   # --no-ff в копии цели
.dpcli/dpcli gc [ВЕТКА|МОДУЛЬ …] [--remove]                    # копии и ветки, уже влитые в основную
```

`sync`, `merge`, `task sync`: незакоммиченный журнал модуля в целевой копии перед слиянием коммитится сам, прочая «грязь» — отказ. Конфликт — слияние отменяется, выводится список файлов.

`gc` пропускает модули с незакрытыми задачами и живыми ветками `<модуль>/*`, грязные копии и копии, на которые ссылаются симлинки; `--remove` делает `git worktree remove` без `--force` и `git branch -d`.

### Задачи

ID задачи: `<КОД>-[этап]<n>[буква]` (`PY-7`, `PY-7a`, `PY-P8`); КОД — `code` модуля (2–4 заглавные латинские, уникален). Без ID `task new` берёт следующий номер модуля (`--stage P` — следующий `<КОД>-P<n>`).

```
.dpcli/dpcli task new <модуль> [ID] --type T --title "…" --goal "…" [--plan-ref "§1"] \
    [--stage P] [--copy К] [--branch Б] [--contract ИМЯ@ВЕРСИЯ] [--scope ПУТЬ] [--dont-touch ПУТЬ] \
    [--test ФИЛЬТР] [--check ИМЯ CMD EXPECT] [--from card.json|-] [--no-copy] [--force]
.dpcli/dpcli task show <ID> [--json] [--full] [--diff]
.dpcli/dpcli task brief <ID> [--review]   # готовое сообщение исполнителю (ревьюеру) — отправлять как есть
.dpcli/dpcli agents                       # реестр агентов: имя, роль, review, источник (dpcli|project|config), модель
.dpcli/dpcli task set <ID> поле=знач поле+=элем поле-=элем [--check ИМЯ CMD EXPECT] [--test Ф] [--drop-check ИМЯ] [--contract ИМЯ@ВЕРСИЯ]
.dpcli/dpcli task note <ID> "правило или заметка"   # дополнение к выданной задаче (видно в task show и inbox <ID>)
.dpcli/dpcli task sync <ID> [--message М] [--trailer Т]   # влить ветку модуля в ветку задачи в её копии
```

Карточка (`<plan_dir>/<модуль>/tasks/<ID>.json`) — обычный JSON: `id, module, type, title, goal, plan_ref, contracts[], copy, branch, base, scope[], dont_touch[], accept[], report_extra[], notes`; можно править руками. `task set` порядок: сначала `--drop-check`, потом `--check`/`--test` (замена проверки одним вызовом); значение — JSON или строка, для списочных полей строка — список через запятую.

`task brief` отказывает (код 1, список недостающего), если у карточки нет `goal`, `scope` или ни одной проверки — карточка не готова к выдаче; `task new` при таких пропусках предупреждает. `EXPECT` проверок разбирается сразу в `task new`/`task set` (неверный — отказ).

Проверка приёмки — `{name, cmd, expect, cwd?, timeout?}` или `{name, tests: "<фильтр>"}` (команда из `checks.tests`). `EXPECT`:

- `exit=0` (по умолчанию);
- `re:<regex>` — есть в выводе; `!re:<regex>` — нет в выводе;
- `num:<regex с группой> <op><число>`, op: `<= >= == < >` — последнее совпадение, запятая читается как точка;
- `tests` — проверка тестами проекта;
- объект: `{"exit":0, "re":"…", "num":"…", "min":…, "max":…}` — все условия сразу.

Команды идут через `bash -c` в копии задачи (если есть; `--here` — в текущей); таймаут по умолчанию 900 с; в окружении `$DPCLI_TASK`.

### События, решения, вопросы

```
.dpcli/dpcli event <ID|модуль> started|reported|accepted|merged|blocked|cancelled|note [--commit h] [--note "…"]
.dpcli/dpcli decide <модуль> "решение" --by user|coordinator|main [--why "…"] [--task ID] [--plan [РАЗДЕЛ]]
.dpcli/dpcli decide <модуль> "вопрос" --ask             # шлюз: вопрос пользователю → Q1
.dpcli/dpcli decide <модуль> "ответ" --by user --answers Q1
.dpcli/dpcli answer <Qn|модуль/Qn> "ответ" [--module М]  # = decide --by user --answers Qn
.dpcli/dpcli questions [--all] [--module М] [--full]     # открытые вопросы по всем модулям
.dpcli/dpcli inbox <модуль|ID> [--by читатель] [--peek] [--max N] [--full]
.dpcli/dpcli log <модуль|ID> [-n N] [--full] [--no-decisions]
```

`--plan` у `decide` дописывает строку в раздел плана («Решения пользователя» по умолчанию). `inbox` показывает новое с прошлого чтения этим читателем (решения, ответы, правки плана, заметки); читатель — `--by`, иначе `$DPCLI_ROLE`, иначе `coordinator` (для ID — `executor`). Метка чтения — `<plan_dir>/<модуль>/.read_<читатель>` (в `.gitignore`).

### Приёмка, отчёт, ревью

```
.dpcli/dpcli accept <ID> [--only ИМЯ] [--here|--cwd DIR] [-j 4] [--commit h] [--dry] [--no-accept] [--no-review] [--full] [--bg [--timeout СЕК]] [--no-tmux] [--tmux-session S]
.dpcli/dpcli report <ID> [файл|-]  |  report <ID> --show [--full]  |  report --template [ID]
.dpcli/dpcli review <ID> --verdict accept|rework --from r.json|-  |  review <ID> --note "итог"  |  review <ID> --show [--full]  |  review --template
```

`accept` печатает таблицу `PASS/FAIL имя значение`, у FAIL — путь к логу (`checks.log_dir/<ID>/`). Всё PASS → событие `accepted`, иначе `checked` с итогом. У типов с `dpcli_review: true` PASS → `checked` (ждёт ревью; `--no-review` — сразу `accepted`; `--here` после слияния ревью не ждёт). `--dry` — пробный прогон без события; `--only` — одна проверка (в конце сводка по всем); `--bg` — через `job` (долгие проверки), ждать: `.dpcli/dpcli job wait dp-accept-<ID> <сек>`.

Строка `scope` в таблице — детерминированная проверка границ: файлы, изменённые в ветке задачи относительно `base` (`git diff --name-only base...HEAD` + незакоммиченные), должны попадать в `scope` и не попадать в `dont_touch` (пункт — glob или файл/префикс каталога; берётся первое слово пункта). Нарушение — FAIL со списком файлов (до 10). Пустой `scope` или копия не на ветке задачи — `SKIP`. Журнал модуля (`<plan_dir>/<модуль>/`, вкл. отчёт), `checks.log_dir` и `gc.ignore_*` нарушением не считаются.

Отчёт (`report --template`): `status` (done|partial|blocked|failed), `summary`, `commits[]`, `checks[{name, value, pass}]`, `not_done[]`, `questions[]`, `images[]`, `how_to_check`, `uncertain`, `dp_feedback`, плюс ключи `report_extra` карточки. Неверный отчёт не сохраняется, ошибка говорит, что не так.

Ревью (`review --template`): `verdict` accept|rework, `summary`, `issues[]` (≤ 7) `{file, line, severity: blocker|major|minor, what, fix}`, `rerun[{name, value, pass}]`. blocker при accept — ошибка.

### План, статус, журнал

```
.dpcli/dpcli plan <модуль|файл.md> [<номер|начало заголовка>] [--contracts] [--depth 3] [--max 150]   # оглавление или раздел
.dpcli/dpcli plan edit <модуль|файл.md> <раздел> --append "текст" | --replace СТАРОЕ НОВОЕ [--all] | --set [ФАЙЛ|-]  [--contracts] [--commit]
.dpcli/dpcli status [<модуль>] [--full] [--stale 40] [--since 30m|2h|today]
.dpcli/dpcli digest [--since today|ДАТА|2h]
.dpcli/dpcli render <модуль> [--out путь|-] [--force]    # md-журнал <plan_dir>/<модуль>/journal.md
```

`plan edit --replace` требует ровно одно вхождение в разделе (`--all` — все); раздел `*` — весь файл (только `--replace`); `--set` без файла или `-` читает stdin. `status`: «тихо» — ни событий, ни коммитов ветки задачи дольше порога (мин).

### Поиск

```
.dpcli/dpcli search <текст|regex> [--module М] [--max N]       # по карточкам, отчётам, событиям, решениям всех модулей
.dpcli/dpcli search --sem "запрос" [--max 10] [--module М|--path ПРЕФИКС] [--all]
.dpcli/dpcli index [--full]                                    # смысловой индекс
```

Перед новой работой полезно `search` по прошлым модулям. Смысловой поиск опционален и по умолчанию выключен (`sem.enabled: false`): без него `search --sem` и `index` сообщают, что поиск выключен, а `merge` в основную ветку индекс не обновляет. Включить: `sem.enabled: true` в конфиге, поставить Ollama и `ollama pull bge-m3`, затем `.dpcli/dpcli index`.
При включении эмбеддинги — через Ollama (`sem.url`, `sem.model`, по умолчанию bge-m3; один раз `ollama pull bge-m3`). Индекс лежит вне git в `sem.cache_dir`, обновляется по хешу текста. `DPCLI_SEM_CPU=1` — считать только на CPU. Корпус — `sem.globs` и журналы dpcli. Нет Ollama или модели — ошибка с подсказкой.

### Документация

```
.dpcli/dpcli docs check                                       # frontmatter, summary, живые ссылки, размер (код 1 при ошибках)
.dpcli/dpcli docs index                                       # собрать INDEX.md и реестры (docs.registries)
.dpcli/dpcli docs find [--type T] [--status S] [--module М] [--archive] [--long] [текст]   # строка «путь — summary»
.dpcli/dpcli docs section <путь>[#раздел] [<номер|начало заголовка>] [--depth 3] [--max N]  # оглавление или раздел
.dpcli/dpcli docs show <путь.md>                              # frontmatter + оглавление
.dpcli/dpcli docs findings [--module М] [текст]               # выводы из registry/findings.md
.dpcli/dpcli docs init [--dry] [--refresh-contracts]          # frontmatter файлам без него (summary: "TODO")
```

Документацию читают по кусочку: `INDEX.md` — точка входа (группы по типу, строка на документ `- [путь](путь) — summary [статус]`, архив — одной строкой), `docs find` — строка на документ, `docs section` — оглавление документа (без раздела) или текст раздела с подразделами, без frontmatter. Раздел — номер из оглавления или начало заголовка; если подходит несколько — список кандидатов и код 1 (`plan` разбирает разделы так же).

Правила `docs check`: `summary` обязательна, одна строка ≤ `docs.summary_max` (140) символов, `TODO` — ошибка (`docs init` ставит `summary: "TODO"`, а не выдумывает из текста); документ больше `docs.max_kb` (40 КБ) — ошибка с подсказкой разбить на разделы-файлы или вынести данные (`docs.max_kb_mode: warn` — только предупреждение; архив и `generated: true` не проверяются). `docs find --status closed|superseded` и `--archive` ищут и в `{docs_dir}/archive/`.

Реестры: `docs.registries` (по умолчанию `[research, contracts]`; `decisions` — только если включён явно, иначе решения ищутся `search`). `registry/findings.md` пишется вручную (`docs index` создаёт заготовку): раздел `## <модуль>`, вывод — пункт `- …` в одну строку с числами и ссылкой `путь#раздел`. Допустимые `type`/`status`, исключения и лимиты — раздел `docs` конфига.

### Долгие запуски и замки

```
.dpcli/dpcli job start <имя> <таймаут_с> <команда…>     # в фоне; rc всегда пишется, 124 — таймаут
.dpcli/dpcli job wait <имя> <таймаут_с>                  # ждёт, печатает код и хвост лога
.dpcli/dpcli job status [имя] [--all]  |  job stop <имя>  |  job attach <имя>
.dpcli/dpcli job --lock cpu|gpu start <имя> <таймаут_с> <команда…>
.dpcli/dpcli lock cpu|gpu <имя> [--timeout СЕК] -- <команда…>
.dpcli/dpcli lock status
```

Логи — `<jobs.dir>/<имя>.{pid,log,rc}`; `rc`: 124 — таймаут, 143 — `job stop`, 129 — окно закрыто пользователем. Замок `cpu` — N слотов (`jobs.cpu_slots` / `DPCLI_CPU_SLOTS`, по умолчанию половина логических ядер), `gpu` — один. Окно tmux по умолчанию (сессия `$DPCLI_TMUX_SESSION`, иначе `jobs.tmux_session`); `--no-tmux` — только фон; нет tmux — предупреждение и обычный фон. Окно закрывается по завершении задачи. Внутри задач tmux отключён (`DPCLI_NO_TMUX=1`).

## Хранение журнала

`<plan_dir>/<модуль>/`:

- `module.json` — модуль: код, ветка, копия, план, контракты;
- `tasks/<ID>.json` — карточка, `tasks/<ID>.report.json` — отчёт исполнителя, `tasks/<ID>.review.json` — последнее ревью;
- `events.jsonl` — события (только дописывание): `{t, by, task, ev, commits?, note?}`;
- `decisions.jsonl` — решения и вопросы: `{t, by, kind: decision|question, text, why?, id?, answers?}`;
- `.read_<читатель>` — метки чтения inbox (вне git);
- `journal.md` — результат `render`.

**Дом журнала** — рабочая копия ветки модуля, если журнал модуля там есть; иначе текущая копия. Поэтому `dpcli` из любой копии (главной, модуля, задачи) читает и пишет один журнал. Коммитит его координатор. `DPCLI_LOCAL=1` — только текущая копия. dpcli сам ничего не коммитит (кроме журнала перед слиянием и `plan edit --commit`).

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `DPCLI_ROLE` | автор событий и читатель inbox по умолчанию (`main`, `coordinator`, `executor`, …) |
| `DPCLI_LOCAL` | `1` — журнал только текущей копии |
| `DPCLI_NO_REEXEC` | `1` — не перезапускаться из главной копии |
| `DPCLI_SESSION` | идентификатор сессии для строки в сообщениях коммитов |
| `DPCLI_TASK` | ID текущей задачи (выставляется в проверках) |
| `DPCLI_COPIES` | каталог рабочих копий вместо `copies_dir` |
| `DPCLI_CPU_SLOTS` | число слотов замка cpu |
| `DPCLI_NO_TMUX` | `1` — не открывать окна tmux |
| `DPCLI_TMUX_SESSION` | сессия tmux для окон |
| `DPCLI_JOB_DIR` | каталог запусков `job` вместо `jobs.dir` |
| `DPCLI_SEM_CPU` | `1` — эмбеддинги только на CPU |

`DPCLI_REEXECED` — служебная (защита от повторного перезапуска).

## Коды выхода

- `0` — успех;
- `1` — ошибка или проверка не прошла (FAIL);
- `2` — неверные аргументы.

Для `job`/`lock` код команды — её собственный код (124 — таймаут).

## Обновление dpcli в проекте

1. Заменить каталог `.dpcli` новой версией (свои файлы в `.dpcli/agents` сохранить или перенести).
2. Выполнить `.dpcli/dpcli init` (или `init --check`, чтобы увидеть, что изменилось; `--force` — перезаписать изменённые вручную файлы).
3. Версия — `VERSION` в `.dpcli/lib/dpcli/__init__.py` (`.dpcli/dpcli --version`).

Устаревшая копия `.dpcli` в рабочей копии задачи перезапускается сама из главной копии (`<главный worktree>/.dpcli/dpcli`), если там `VERSION` новее: в stderr одна строка, аргументы и cwd сохраняются. Отключить — `DPCLI_NO_REEXEC=1`. Поэтому обновлять достаточно главную копию.
